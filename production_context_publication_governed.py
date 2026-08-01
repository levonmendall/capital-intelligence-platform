"""Decision-complete production publication for the listed-wrapper paper pilot."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Callable, Mapping
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
from cio import RecommendationUniversePolicy
from cio.persistence import serialize_candidate_decision, serialize_opportunity_queue
from governance.bounded_pilot_scope import BoundedPilotCapabilityAuthority
from evaluation.opportunity_outcomes import SQLiteOpportunityOutcomeStore
from opportunity import AlternativeKind, AlternativeUse, OpportunityEngine, OpportunitySetContext
from opportunity.competitive import prepare_competitive_opportunity_set
from operations.direct_global_markets import load_direct_global_market_universe
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryResult,
    discover_comprehensive_markets,
)
from operations.equity_discovery import (
    EquityDiscoveryResult,
    discover_us_equities,
)
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
    write_active_paper_universe,
)
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

STATE_SCHEMA = "production-context-publication-state.v5-comprehensive-markets"

EquityDiscoveryProbe = Callable[..., EquityDiscoveryResult]
ComprehensiveDiscoveryProbe = Callable[..., ComprehensiveMarketDiscoveryResult]


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
        instrument_count=int(state.get("instrument_count", instrument_count)),
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
    equity_discovery_probe: EquityDiscoveryProbe | None = None,
    comprehensive_discovery_probe: ComprehensiveDiscoveryProbe | None = None,
    clock: Clock | None = None,
) -> ProductionContextPublicationResult:
    """Publish cross-asset wrappers plus dynamically discovered company equities."""

    scheduled = _aware(scheduled_for, field_name="scheduled_for")
    cycle_key = _cycle_key(
        scheduled_for=scheduled,
        timezone_name=settings.scheduler_timezone,
    )
    base_universe = load_free_paper_pilot_universe(universe_path)
    universe = base_universe
    reused = _reuse(
        settings=settings,
        cycle_key=cycle_key,
        scheduled_for=scheduled,
        instrument_count=len(universe.instruments),
    )
    if reused is not None:
        return reused

    try:
        readiness = (readiness_probe or _default_readiness_probe)(base_universe)
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
    expected_symbols = tuple(sorted(item.symbol for item in base_universe.instruments))
    quote_symbols = tuple(sorted(str(item[0]).upper() for item in quote_timestamps))
    if (
        not configuration_ready
        or tuple(sorted(validated_symbols)) != expected_symbols
        or quote_symbols != expected_symbols
        or len(quote_timestamps) != len(base_universe.instruments)
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
    maximum_future_skew = timedelta(seconds=60 if clock is None else 0)
    if any(timestamp > now + maximum_future_skew for timestamp in quote_datetimes):
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

    stamp = _stamp(decision_as_of)
    eligible_identifier = f"eligible-universe:paper-pilot:{stamp}"
    screening_cycle_identifier = f"screening:paper-pilot:{stamp}"
    screening_publication_identifier = f"publication:paper-pilot:{stamp}"
    context_identifier = f"production-context:paper-pilot:{stamp}"
    opportunity_identifier = f"opportunity:paper-pilot:{stamp}"

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
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=f"Canonical portfolio preparation failed: {type(error).__name__}: {error}",
            instrument_count=len(base_universe.instruments),
        )

    outcome_store = SQLiteOpportunityOutcomeStore(
        settings.portfolio_database.with_name("opportunity_outcomes.db")
    )
    try:
        tracked_symbols = outcome_store.unresolved_symbols(as_of=decision_as_of)
    except (OSError, TypeError, ValueError):
        tracked_symbols = ()

    discovery: EquityDiscoveryResult | None = None
    base_symbols = set(base_universe.symbol_map)
    held_symbols = tuple(position.symbol for position in tentative.positions)
    dynamic_holdings = tuple(symbol for symbol in held_symbols if symbol not in base_symbols)
    try:
        discovery = (equity_discovery_probe or discover_us_equities)(
            as_of=decision_as_of,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=tuple(base_symbols),
        )
        discovered = discovery.instruments_for_holdings(held_symbols)
        fully_injected_publication = all(
            item is not None
            for item in (
                readiness_probe,
                cash_probe,
                evidence_probe,
                equity_discovery_probe,
                clock,
            )
        )
        if comprehensive_discovery_probe is None and fully_injected_publication:
            direct_universe = load_direct_global_market_universe()

            class _InjectedComprehensiveDiscovery:
                identifier = f"injected-publication:{direct_universe.identifier}"
                manifest_fingerprint = direct_universe.identifier
                policy_version = direct_universe.schema_version
                lanes = ()

                @staticmethod
                def instruments_for_holdings(_held_symbols):
                    return direct_universe.instruments

            comprehensive = _InjectedComprehensiveDiscovery()
        else:
            comprehensive = (comprehensive_discovery_probe or discover_comprehensive_markets)(
                as_of=decision_as_of,
                held_symbols=held_symbols,
                tracked_symbols=tracked_symbols,
                excluded_symbols=tuple((*base_symbols, *(item.symbol for item in discovered))),
            )
        comprehensive_instruments = comprehensive.instruments_for_holdings(held_symbols)
        universe = replace(
            base_universe,
            identifier=(
                f"{base_universe.identifier}+{discovery.identifier}"
                f"+{comprehensive.identifier}"
            ),
            objective=(
                base_universe.objective
                + " Daily broad U.S.-company and comprehensive global-market discovery compete for capital."
            ),
            instruments=tuple(
                (*base_universe.instruments, *discovered, *comprehensive_instruments)
            ),
            limitations=tuple(
                dict.fromkeys(
                    (*base_universe.limitations,
                     "Individual U.S. equities enter through broad SEC/Alpaca discovery and begin with a 1% exploratory cap.",
                     "International equities, complete FX and crypto catalogs, dated futures chains, direct bonds, and long-premium defined-risk options enter through comprehensive point-in-time discovery.",
                     "Discovery can nominate instruments but cannot choose an action, size a position, construct a portfolio, authorize execution, or enable real money.")
                )
            ),
        )
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=(
                "Complete opportunity search is unavailable; a no-superior-opportunity "
                "conclusion is prohibited until broad U.S.-equity discovery completes and six-lane global discovery completes: "
                f"{type(error).__name__}: {error}"
            ),
            instrument_count=len(base_universe.instruments),
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
            detail=f"Cross-market evidence collection failed: {type(error).__name__}: {error}",
            instrument_count=len(universe.instruments),
        )

    completed_at = _aware(
        (clock or (lambda: datetime.now(tz=scheduled.tzinfo)))(),
        field_name="clock",
    )
    if completed_at < decision_as_of:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail="The evidence collection clock moved backward.",
            instrument_count=len(universe.instruments),
        )
    decision_as_of = completed_at
    if (
        decision_as_of.astimezone(ZoneInfo(settings.scheduler_timezone)).date()
        != scheduled.astimezone(ZoneInfo(settings.scheduler_timezone)).date()
    ):
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail="The governed evidence collection crossed the scheduled market date.",
            instrument_count=len(universe.instruments),
        )

    stamp = _stamp(decision_as_of)
    eligible_identifier = f"eligible-universe:paper-pilot:{stamp}"
    screening_cycle_identifier = f"screening:paper-pilot:{stamp}"
    screening_publication_identifier = f"publication:paper-pilot:{stamp}"
    context_identifier = f"production-context:paper-pilot:{stamp}"
    opportunity_identifier = f"opportunity:paper-pilot:{stamp}"
    try:
        tentative, already_persisted = _tentative_portfolio(
            store=portfolio_store,
            decision_as_of=decision_as_of,
            context_identifier=context_identifier,
        )
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=f"Canonical portfolio finalization failed: {type(error).__name__}: {error}",
            instrument_count=len(universe.instruments),
        )

    outcome_resolution_count = 0
    if discovery is not None:
        try:
            outcome_resolution_count = outcome_store.resolve_due(
                observed_at=decision_as_of,
                observed_prices={
                    symbol: (price, source)
                    for symbol, price, source in discovery.observed_prices
                },
            )
        except (OSError, TypeError, ValueError):
            outcome_resolution_count = 0

    catalog_identifier = f"catalog:{universe.identifier}"
    master_snapshot_identifier = (
        f"alpaca-paper-assets:{stamp}"
        if discovery is None
        else discovery.security_master_snapshot_identifier
    )

    try:
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
        source_versions=tuple(
            (
                ("free_paper_pilot_universe", base_universe.identifier),
                (
                    "alpaca_paper_account",
                    str(_report_value(readiness, "account_status", "ACTIVE")).upper(),
                ),
                ("alpaca_iex_quote_date", latest_quote_date),
                ("alpaca_iex_historical_bars", "v2-stocks-bars"),
                ("fred_macro", "DGS10,T10Y2Y,VIXCLS,DFF"),
            )
            + (() if discovery is None else (
                ("broad_us_equity_discovery", discovery.identifier),
                ("sec_company_master", discovery.security_master_snapshot_identifier),
                ("comprehensive_market_discovery", comprehensive.identifier),
                ("comprehensive_market_manifest", comprehensive.manifest_fingerprint),
            ))
        ),
        model_versions=(
            ("eligible_universe_policy", universe.schema_version),
            ("wrapper_candidate_admission", "listed-wrapper-evidence.v1"),
            ("company_candidate_admission", "sec-company-equity-evidence.v1"),
            ("equity_discovery", "disabled" if discovery is None else discovery.policy_version),
            ("comprehensive_market_discovery", comprehensive.policy_version),
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
    try:
        write_active_paper_universe(
            universe,
            eligible_universe_publication_identifier=eligible_identifier,
            destination=settings.portfolio_database.with_name("active-paper-universe.json"),
        )
    except (OSError, TypeError, ValueError) as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=decision_as_of,
            detail=f"Active paper execution universe could not be persisted: {error}",
            instrument_count=len(universe.instruments),
        )

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
    baseline_opportunity_context = OpportunitySetContext(
        identifier=opportunity_identifier,
        as_of=decision_as_of,
        alternatives=tuple(alternatives),
    )
    capability_authority = BoundedPilotCapabilityAuthority.from_universe(base_universe)
    opportunity_engine = OpportunityEngine(
        universe_policy=RecommendationUniversePolicy(
            asset_class_authority=capability_authority,
        )
    )
    competitive = prepare_competitive_opportunity_set(
        opportunity_engine,
        build_result.candidates,
        baseline_opportunity_context,
    )
    # Candidate evidence is immutable; only its point-in-time opportunity-cost field
    # is reconciled to the same current cash/holding baseline consumed by qualification.
    build_result = replace(build_result, candidates=competitive.candidates)
    opportunity_context = competitive.context
    queue = competitive.queue
    try:
        outcome_store.append_screening_decisions(
            queue=queue,
            candidates=build_result.candidates,
            cash_annual_return=cash_expected_return,
        )
        outcome_summary = outcome_store.summary()
    except (OSError, TypeError, ValueError):
        outcome_summary = None
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
    opportunity_queue_payload = {
        **serialize_opportunity_queue(
            queue,
            occurred_at=decision_as_of,
        ),
        "candidate_alternative_identifiers": list(
            competitive.candidate_alternative_identifiers
        ),
    }
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
        opportunity_queue_payload=opportunity_queue_payload,
    )
    start_payload = {
        "cycle_identifier": screening_cycle_identifier,
        "scheduled_for": scheduled.isoformat(),
        "started_at": decision_as_of.isoformat(),
        "as_of": decision_as_of.isoformat(),
        "knowledge_cutoff": decision_as_of.isoformat(),
        "metrics_provider": "ALPACA_PAPER_IEX_HISTORICAL_AND_QUOTES",
        "candidate_provider": "GOVERNED_WRAPPER_AND_COMPANY_EVIDENCE_V1",
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
        "capability_policy": capability_authority.coverage_payload(),
        "baseline_opportunity_cost": competitive.baseline_opportunity_cost,
        "qualified_candidate_alternative_count": len(
            competitive.candidate_alternative_identifiers
        ),
        "holding_evidence_count": len(build_result.holding_evidence),
        "instrument_count": len(universe.instruments),
        "comprehensive_discovery_identifier": comprehensive.identifier,
        "comprehensive_discovery_manifest_fingerprint": comprehensive.manifest_fingerprint,
        "comprehensive_discovery_lane_counts": {
            lane.asset_class.value: {
                "catalog": lane.catalog_count,
                "deep": lane.deep_analyzed_count,
                "selected": len(lane.selected),
            }
            for lane in comprehensive.lanes
        },
        "opportunity_outcomes": (
            {"state": "unavailable", "resolved_this_cycle": outcome_resolution_count}
            if outcome_summary is None
            else {
                "state": "available",
                "recorded_decisions": outcome_summary.recorded_decisions,
                "resolved_outcomes": outcome_summary.resolved_outcomes,
                "missed_opportunities": outcome_summary.missed_opportunities,
                "avoided_losses": outcome_summary.avoided_losses,
                "resolved_this_cycle": outcome_resolution_count,
            }
        ),
        "equity_discovery": (
            {"state": "unavailable", "selected_count": 0}
            if discovery is None
            else {
                "state": "available",
                "identifier": discovery.identifier,
                "screened_asset_count": discovery.screened_asset_count,
                "snapshot_covered_count": discovery.snapshot_covered_count,
                "selected_count": len(discovery.selected),
            }
        ),
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
            "Certified strategic cross-asset wrappers and the daily broad U.S.-company "
            "discovery lane, published complete candidate and exclusion screening, "
            "marked the canonical portfolio, and persisted company-specific evidence."
        ),
        eligible_universe_identifier=eligible_identifier,
        screening_publication_identifier=screening_publication_identifier,
        context_identifier=context_identifier,
        instrument_count=len(universe.instruments),
        candidate_count=len(candidate_results),
        exclusion_count=len(exclusion_results),
    )


__all__ = ["prepare_governed_production_context_for_cycle"]
