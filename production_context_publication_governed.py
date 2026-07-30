"""Decision-complete production publication for the listed-wrapper paper pilot."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from api.config import ApiSettings
from application import (
    EvidenceCertificationState,
    GovernedEvidenceLineage,
    ProductionContextEvidenceSnapshot,
    SQLiteProductionContextStore,
)
from application.eligible_universe import (
    CertifiedEligibleUniversePublication,
    EligibleUniverseCertificationState,
    SQLiteCertifiedEligibleUniverseStore,
)
from cio.persistence import serialize_candidate_decision, serialize_opportunity_queue
from opportunity import AlternativeKind, AlternativeUse, OpportunityEngine, OpportunitySetContext
from operations.free_paper_pilot import DEFAULT_UNIVERSE_PATH, load_free_paper_pilot_universe
from portfolio.state import SQLiteCanonicalPortfolioStore
from production_paper_evidence import (
    EvidenceProbe,
    ProductionPaperEvidenceError,
    build_paper_evidence,
    collect_paper_evidence,
)
from screening import (
    FullUniverseScreeningPublication,
    InstrumentScreeningResult,
    SQLiteFullUniverseScreeningStore,
    ScreeningDisposition,
    ScreeningEventType,
)

from production_context_publication_runtime import (
    CashProbe,
    Clock,
    ProductionContextPublicationResult,
    ReadinessProbe,
    _atomic_json,
    _aware,
    _cycle_key,
    _default_cash_probe,
    _default_readiness_probe,
    _load_json,
    _report_value,
    _stamp,
    _state_path,
)

STATE_SCHEMA = "production-context-publication-state.v2"


def _blocked(
    *,
    cycle_key: str,
    scheduled_for: datetime,
    detail: str,
    instrument_count: int,
    decision_as_of: datetime | None = None,
) -> ProductionContextPublicationResult:
    return ProductionContextPublicationResult(
        state="blocked",
        cycle_key=cycle_key,
        scheduled_for=scheduled_for,
        decision_as_of=decision_as_of,
        detail=detail,
        instrument_count=instrument_count,
    )


def _reuse(
    *,
    settings: ApiSettings,
    cycle_key: str,
    scheduled_for: datetime,
    instrument_count: int,
) -> ProductionContextPublicationResult | None:
    state = _load_json(_state_path(settings))
    if (
        state is None
        or state.get("schema_version") != STATE_SCHEMA
        or state.get("cycle_key") != cycle_key
    ):
        return None
    raw = state.get("decision_as_of")
    if not isinstance(raw, str):
        return None
    decision_as_of = _aware(
        datetime.fromisoformat(raw),
        field_name="decision_as_of",
    )
    eligible_identifier = str(state.get("eligible_universe_identifier") or "")
    screening_cycle = str(state.get("screening_cycle_identifier") or "")
    publication_identifier = str(state.get("screening_publication_identifier") or "")
    context_identifier = str(state.get("context_identifier") or "")
    if not all(
        (eligible_identifier, screening_cycle, publication_identifier, context_identifier)
    ):
        return None
    eligible_store = SQLiteCertifiedEligibleUniverseStore(
        settings.portfolio_database.with_name("eligible_universe.db")
    )
    screening_store = SQLiteFullUniverseScreeningStore(
        settings.full_universe_screening_database
    )
    context_store = SQLiteProductionContextStore(
        settings.portfolio_database.with_name("production_context.db")
    )
    portfolio_store = SQLiteCanonicalPortfolioStore(settings.portfolio_database)
    context = context_store.snapshot_for_as_of(
        portfolio_code="COMPOUNDING",
        as_of=decision_as_of,
    )
    portfolio_matches = tuple(
        item
        for item in portfolio_store.history("COMPOUNDING", limit=10_000)
        if item.as_of == decision_as_of
    )
    publication = screening_store.publication(screening_cycle)
    if (
        eligible_store.publication(eligible_identifier) is None
        or publication is None
        or publication.identifier != publication_identifier
        or context is None
        or len(portfolio_matches) != 1
    ):
        return None
    return ProductionContextPublicationResult(
        state="reused",
        cycle_key=cycle_key,
        scheduled_for=scheduled_for,
        decision_as_of=decision_as_of,
        detail=(
            "The certified listed-wrapper universe, complete screening, exact-time "
            "portfolio, candidate evidence, and holding evidence were already persisted."
        ),
        eligible_universe_identifier=eligible_identifier,
        screening_publication_identifier=publication_identifier,
        context_identifier=context_identifier,
        instrument_count=instrument_count,
        candidate_count=publication.candidate_count,
        exclusion_count=publication.excluded_count,
    )


def _tentative_portfolio(
    *,
    store: SQLiteCanonicalPortfolioStore,
    decision_as_of: datetime,
    context_identifier: str,
):
    store.verify_integrity()
    matches = tuple(
        item
        for item in store.history("COMPOUNDING", limit=10_000)
        if item.as_of == decision_as_of
    )
    if len(matches) > 1:
        raise ProductionPaperEvidenceError(
            "multiple canonical portfolio snapshots exist at the decision timestamp"
        )
    if matches:
        return matches[0], True
    latest = store.latest("COMPOUNDING")
    if latest is None:
        raise ProductionPaperEvidenceError("canonical portfolio state is unavailable")
    if latest.as_of > decision_as_of:
        raise ProductionPaperEvidenceError("canonical portfolio state is future-known")
    if latest.currency_balances:
        raise ProductionPaperEvidenceError(
            "the USD listed-wrapper pilot cannot publish non-base currency balances"
        )
    if latest.cash_amount <= 0.0:
        raise ProductionPaperEvidenceError(
            "canonical portfolio must retain positive cash"
        )
    return (
        replace(
            latest,
            identifier=f"portfolio:compounding:decision:{_stamp(decision_as_of)}",
            as_of=decision_as_of,
            source_identifiers=tuple(
                dict.fromkeys((*latest.source_identifiers, context_identifier))
            ),
        ),
        False,
    )


def _mark_portfolio(snapshot, build_result, *, decision_as_of: datetime):
    prices = {
        item.instrument.symbol: item.current_price
        for item in build_result.candidates
    }
    missing = sorted(
        position.symbol
        for position in snapshot.positions
        if position.symbol not in prices
    )
    if missing:
        raise ProductionPaperEvidenceError(
            f"current marks are unavailable for canonical holdings: {missing}"
        )
    return replace(
        snapshot,
        positions=tuple(
            replace(
                position,
                mark_price=prices[position.symbol],
                updated_at=decision_as_of,
            )
            for position in snapshot.positions
        ),
    )


def prepare_governed_production_context_for_cycle(
    *,
    settings: ApiSettings,
    scheduled_for: datetime,
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    readiness_probe: ReadinessProbe | None = None,
    cash_probe: CashProbe | None = None,
    evidence_probe: EvidenceProbe | None = None,
    clock: Clock | None = None,
) -> ProductionContextPublicationResult:
    """Publish complete listed-wrapper candidate and holding evidence for one cycle."""

    scheduled = _aware(scheduled_for, field_name="scheduled_for")
    cycle_key = _cycle_key(
        scheduled_for=scheduled,
        timezone_name=settings.scheduler_timezone,
    )
    universe = load_free_paper_pilot_universe(universe_path)
    reused = _reuse(
        settings=settings,
        cycle_key=cycle_key,
        scheduled_for=scheduled,
        instrument_count=len(universe.instruments),
    )
    if reused is not None:
        return reused

    try:
        readiness = (readiness_probe or _default_readiness_probe)(universe)
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            detail=f"Paper-universe provider certification failed: {type(error).__name__}",
            instrument_count=len(universe.instruments),
        )
    configuration_ready = bool(
        _report_value(readiness, "configuration_ready", False)
    )
    validated_symbols = tuple(
        str(item).upper()
        for item in _report_value(readiness, "validated_symbols", ())
    )
    quote_timestamps = tuple(
        tuple(item)
        for item in _report_value(readiness, "quote_timestamps", ())
    )
    expected_symbols = tuple(sorted(item.symbol for item in universe.instruments))
    quote_symbols = tuple(sorted(str(item[0]).upper() for item in quote_timestamps))
    if (
        not configuration_ready
        or tuple(sorted(validated_symbols)) != expected_symbols
        or quote_symbols != expected_symbols
        or len(quote_timestamps) != len(universe.instruments)
    ):
        blockers = tuple(
            str(item) for item in _report_value(readiness, "blockers", ())
        )
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            detail=(
                blockers[0]
                if blockers
                else "Alpaca paper assets and IEX quote coverage are incomplete."
            ),
            instrument_count=len(universe.instruments),
        )

    try:
        cash_observation = (cash_probe or _default_cash_probe)()
        cash_date = str(_report_value(cash_observation, "date", "")).strip()
        cash_value = float(_report_value(cash_observation, "value"))
        if not cash_date or not isfinite(cash_value):
            raise ValueError("cash observation is incomplete")
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            detail=f"Certified cash-return evidence failed: {type(error).__name__}",
            instrument_count=len(universe.instruments),
        )

    try:
        quote_datetimes = tuple(
            _aware(
                datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")),
                field_name="quote_timestamp",
            )
            for _symbol, timestamp in quote_timestamps
        )
    except (TypeError, ValueError) as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            detail=f"Paper quote timestamps are invalid: {type(error).__name__}",
            instrument_count=len(universe.instruments),
        )
    now = _aware((clock or (lambda: datetime.now(tz=scheduled.tzinfo)))(), field_name="clock")
    if any(timestamp > now + timedelta(seconds=5) for timestamp in quote_datetimes):
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            detail="Paper-universe quote evidence is future-known.",
            instrument_count=len(universe.instruments),
        )
    decision_as_of = now
    if decision_as_of < scheduled:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail="The governed publication was requested before the CIO schedule.",
            instrument_count=len(universe.instruments),
        )
    if (
        decision_as_of.astimezone(ZoneInfo(settings.scheduler_timezone)).date()
        != scheduled.astimezone(ZoneInfo(settings.scheduler_timezone)).date()
    ):
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail="The governed publication window crossed the scheduled market date.",
            instrument_count=len(universe.instruments),
        )

    cash_expected_return = round(max(-1.0, min(1.0, cash_value / 100.0)), 8)
    try:
        evidence_payload = collect_paper_evidence(
            universe,
            decision_as_of,
            probe=evidence_probe,
        )
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=f"Listed-wrapper evidence collection failed: {type(error).__name__}: {error}",
            instrument_count=len(universe.instruments),
        )

    stamp = _stamp(decision_as_of)
    eligible_identifier = f"eligible-universe:paper-pilot:{stamp}"
    screening_cycle_identifier = f"screening:paper-pilot:{stamp}"
    screening_publication_identifier = f"publication:paper-pilot:{stamp}"
    context_identifier = f"production-context:paper-pilot:{stamp}"
    opportunity_identifier = f"opportunity:paper-pilot:{stamp}"
    catalog_identifier = f"catalog:{universe.identifier}"
    master_snapshot_identifier = f"alpaca-paper-assets:{stamp}"

    eligible_store = SQLiteCertifiedEligibleUniverseStore(
        settings.portfolio_database.with_name("eligible_universe.db")
    )
    screening_store = SQLiteFullUniverseScreeningStore(
        settings.full_universe_screening_database
    )
    context_store = SQLiteProductionContextStore(
        settings.portfolio_database.with_name("production_context.db")
    )
    portfolio_store = SQLiteCanonicalPortfolioStore(settings.portfolio_database)

    try:
        tentative, already_persisted = _tentative_portfolio(
            store=portfolio_store,
            decision_as_of=decision_as_of,
            context_identifier=context_identifier,
        )
        preliminary = build_paper_evidence(
            universe=universe,
            decision_as_of=decision_as_of,
            cash_expected_return=cash_expected_return,
            portfolio=tentative,
            payload=evidence_payload,
        )
        marked = _mark_portfolio(
            tentative,
            preliminary,
            decision_as_of=decision_as_of,
        )
        build_result = build_paper_evidence(
            universe=universe,
            decision_as_of=decision_as_of,
            cash_expected_return=cash_expected_return,
            portfolio=marked,
            payload=evidence_payload,
        )
        if already_persisted:
            if marked != tentative:
                raise ProductionPaperEvidenceError(
                    "persisted exact-time portfolio marks conflict with current evidence"
                )
        else:
            portfolio_store.append(marked)
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=f"Candidate or holding evidence failed closed: {type(error).__name__}: {error}",
            instrument_count=len(universe.instruments),
        )

    latest_quote_date = max(quote_datetimes).date().isoformat()
    eligible = CertifiedEligibleUniversePublication(
        identifier=eligible_identifier,
        published_at=decision_as_of,
        as_of=decision_as_of,
        knowledge_cutoff=decision_as_of,
        security_master_catalog_identifier=catalog_identifier,
        security_master_snapshot_identifier=master_snapshot_identifier,
        policy_version=universe.schema_version,
        certification_identifier=f"certification:paper-pilot:{stamp}",
        certification_state=EligibleUniverseCertificationState.APPROVED,
        certification_expires_at=decision_as_of + timedelta(days=1),
        eligible_instrument_identifiers=tuple(
            item.instrument_identifier for item in universe.instruments
        ),
        source_versions=(
            ("free_paper_pilot_universe", universe.identifier),
            (
                "alpaca_paper_account",
                str(_report_value(readiness, "account_status", "ACTIVE")).upper(),
            ),
            ("alpaca_iex_quote_date", latest_quote_date),
            ("alpaca_iex_historical_bars", "v2-stocks-bars"),
            ("fred_macro", "DGS10,T10Y2Y,VIXCLS,FEDFUNDS"),
        ),
        model_versions=(
            ("eligible_universe_policy", universe.schema_version),
            ("candidate_admission", "listed-wrapper-evidence.v1"),
        ),
        instrument_approval_identifiers=tuple(
            (
                item.instrument_identifier,
                f"paper-policy:{universe.identifier}:{item.symbol}",
            )
            for item in universe.instruments
        ),
    )
    eligible_store.append(eligible)

    cash_weight = round(marked.cash_amount / marked.nav, 8)
    holding_by_symbol = {
        item.symbol: item for item in build_result.holding_evidence
    }
    alternatives: list[AlternativeUse] = [
        AlternativeUse(
            identifier="cash",
            kind=AlternativeKind.CASH,
            expected_return=cash_expected_return,
            implementation_cost_return=0.0,
            evidence_quality=0.95,
            liquidity_score=1.0,
            current_weight=cash_weight,
        )
    ]
    alternatives.extend(
        AlternativeUse(
            identifier=f"holding:{position.symbol}",
            kind=AlternativeKind.CURRENT_HOLDING,
            expected_return=holding_by_symbol[position.symbol].expected_return,
            implementation_cost_return=holding_by_symbol[
                position.symbol
            ].implementation_cost_return,
            evidence_quality=holding_by_symbol[position.symbol].evidence_quality,
            liquidity_score=holding_by_symbol[position.symbol].liquidity_score,
            current_weight=round(position.market_value / marked.nav, 8),
        )
        for position in marked.positions
    )
    alternatives.extend(
        AlternativeUse(
            identifier=candidate.identifier,
            kind=AlternativeKind.QUALIFIED_CANDIDATE,
            expected_return=candidate.probability_weighted_expected_return,
            implementation_cost_return=candidate.implementation_cost_return,
            evidence_quality=candidate.evidence_quality.score,
            liquidity_score=candidate.liquidity_score,
            current_weight=0.0,
        )
        for candidate in build_result.candidates
    )
    opportunity_context = OpportunitySetContext(
        identifier=opportunity_identifier,
        as_of=decision_as_of,
        alternatives=tuple(alternatives),
    )
    queue = OpportunityEngine().build_queue(
        build_result.candidates,
        opportunity_context,
    )
    candidate_by_instrument = {
        item.instrument.instrument_id: item for item in build_result.candidates
    }
    exclusion_by_instrument = dict(build_result.exclusions)
    instrument_results: list[InstrumentScreeningResult] = []
    for instrument in universe.instruments:
        candidate = candidate_by_instrument.get(instrument.instrument_identifier)
        if candidate is not None:
            instrument_results.append(
                InstrumentScreeningResult(
                    cycle_identifier=screening_cycle_identifier,
                    partition_index=0,
                    instrument_identifier=instrument.instrument_identifier,
                    symbol=instrument.symbol,
                    disposition=ScreeningDisposition.CANDIDATE,
                    completed_at=decision_as_of,
                    candidate_payload=serialize_candidate_decision(candidate),
                )
            )
        else:
            reasons = exclusion_by_instrument.get(
                instrument.instrument_identifier,
                ("Certified listed-wrapper evidence is unavailable.",),
            )
            instrument_results.append(
                InstrumentScreeningResult(
                    cycle_identifier=screening_cycle_identifier,
                    partition_index=0,
                    instrument_identifier=instrument.instrument_identifier,
                    symbol=instrument.symbol,
                    disposition=ScreeningDisposition.EXCLUDED,
                    completed_at=decision_as_of,
                    reasons=reasons,
                )
            )
    candidate_results = tuple(
        item
        for item in instrument_results
        if item.disposition is ScreeningDisposition.CANDIDATE
    )
    exclusion_results = tuple(
        item
        for item in instrument_results
        if item.disposition is ScreeningDisposition.EXCLUDED
    )
    screening_publication = FullUniverseScreeningPublication(
        identifier=screening_publication_identifier,
        cycle_identifier=screening_cycle_identifier,
        published_at=decision_as_of,
        security_master_catalog_identifier=catalog_identifier,
        security_master_snapshot_identifier=master_snapshot_identifier,
        universe_snapshot_identifier=eligible_identifier,
        opportunity_context_identifier=opportunity_identifier,
        eligible_instrument_count=len(universe.instruments),
        screened_instrument_count=len(universe.instruments),
        candidate_count=len(candidate_results),
        excluded_count=len(exclusion_results),
        candidate_payloads=tuple(
            dict(item.candidate_payload or {}) for item in candidate_results
        ),
        exclusions=tuple(item.to_dict() for item in exclusion_results),
        opportunity_queue_payload=serialize_opportunity_queue(
            queue,
            occurred_at=decision_as_of,
        ),
    )
    start_payload = {
        "cycle_identifier": screening_cycle_identifier,
        "scheduled_for": scheduled.isoformat(),
        "started_at": decision_as_of.isoformat(),
        "as_of": decision_as_of.isoformat(),
        "knowledge_cutoff": decision_as_of.isoformat(),
        "metrics_provider": "ALPACA_PAPER_IEX_HISTORICAL_AND_QUOTES",
        "candidate_provider": "GOVERNED_LISTED_WRAPPER_EVIDENCE_V1",
        "catalog_identifier": catalog_identifier,
        "security_master_snapshot_identifier": master_snapshot_identifier,
        "universe_snapshot_identifier": eligible_identifier,
        "policy_version": universe.schema_version,
        "opportunity_context_identifier": opportunity_identifier,
        "eligible_instrument_count": len(universe.instruments),
        "structural_exclusion_count": len(exclusion_results),
        "partition_size": len(universe.instruments),
        "maximum_partition_attempts": 1,
    }
    screening_store.append_many(
        (
            (
                f"{screening_cycle_identifier}:start",
                screening_cycle_identifier,
                ScreeningEventType.CYCLE_STARTED,
                decision_as_of,
                start_payload,
            ),
            *tuple(
                (
                    item.event_identifier,
                    screening_cycle_identifier,
                    ScreeningEventType.INSTRUMENT_RESULT,
                    decision_as_of,
                    item.to_dict(),
                )
                for item in instrument_results
            ),
            (
                f"{screening_cycle_identifier}:publication",
                screening_cycle_identifier,
                ScreeningEventType.PUBLICATION,
                decision_as_of,
                screening_publication.to_dict(),
            ),
        )
    )

    cash_lineage = GovernedEvidenceLineage(
        certification_identifier=f"certification:fred:dgs10:{cash_date}",
        certification_state=EvidenceCertificationState.APPROVED,
        certification_expires_at=decision_as_of + timedelta(days=7),
        fresh_until=decision_as_of + timedelta(days=1),
        evidence_identifiers=(f"fred:DGS10:{cash_date}",),
        source_versions=(("FRED:DGS10", cash_date),),
        model_versions=(("cash_expected_return", "dgs10-yield.v1"),),
    )
    all_candidate_evidence = build_result.candidate_evidence_by_identifier
    qualified_identifiers = tuple(
        item.candidate.identifier for item in queue.ranked
    )
    context_store.append(
        ProductionContextEvidenceSnapshot(
            identifier=context_identifier,
            screening_cycle_identifier=screening_cycle_identifier,
            portfolio_code="COMPOUNDING",
            as_of=decision_as_of,
            knowledge_cutoff=decision_as_of,
            cash_expected_return=cash_expected_return,
            cash_evidence_quality=0.95,
            cash_liquidity_score=1.0,
            cash_lineage=cash_lineage,
            candidate_evidence=tuple(
                all_candidate_evidence[identifier]
                for identifier in qualified_identifiers
            ),
            holding_evidence=build_result.holding_evidence,
        )
    )

    state_payload = {
        "schema_version": STATE_SCHEMA,
        "cycle_key": cycle_key,
        "scheduled_for": scheduled.isoformat(),
        "decision_as_of": decision_as_of.isoformat(),
        "eligible_universe_identifier": eligible_identifier,
        "screening_cycle_identifier": screening_cycle_identifier,
        "screening_publication_identifier": screening_publication_identifier,
        "context_identifier": context_identifier,
        "candidate_count": len(candidate_results),
        "exclusion_count": len(exclusion_results),
        "qualified_candidate_count": len(qualified_identifiers),
        "holding_evidence_count": len(build_result.holding_evidence),
        "paper_only": True,
        "real_money_authorized": False,
    }
    _atomic_json(_state_path(settings), state_payload)

    return ProductionContextPublicationResult(
        state="ready",
        cycle_key=cycle_key,
        scheduled_for=scheduled,
        decision_as_of=decision_as_of,
        detail=(
            "Certified the approved listed-wrapper universe, published complete "
            "candidate and exclusion screening, marked the canonical portfolio, and "
            "persisted exact candidate and holding evidence for CIO comparison."
        ),
        eligible_universe_identifier=eligible_identifier,
        screening_publication_identifier=screening_publication_identifier,
        context_identifier=context_identifier,
        instrument_count=len(universe.instruments),
        candidate_count=len(candidate_results),
        exclusion_count=len(exclusion_results),
    )


__all__ = ["prepare_governed_production_context_for_cycle"]
