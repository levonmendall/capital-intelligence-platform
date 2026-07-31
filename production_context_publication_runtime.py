"""Governed pre-CIO publication for the active free-data paper deployment.

The production scheduler consumes only persisted, certified authorities.  This module
creates those authorities from the already-approved paper universe and live provider
readiness without manufacturing an investment candidate.  Instruments lacking a
certified candidate packet are explicitly excluded, which allows the CIO to publish a
truthful no-action briefing while preserving every fail-closed boundary.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
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
from cio.persistence import serialize_opportunity_queue
from opportunity import AlternativeKind, AlternativeUse, OpportunityEngine, OpportunitySetContext
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    FreePaperPilotUniverse,
    assess_free_paper_pilot_readiness,
    load_free_paper_pilot_universe,
)
from portfolio.state import (
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)
from providers.alpaca_paper import create_alpaca_paper_client
from providers.fred import FREDProvider
from screening import (
    FullUniverseScreeningPublication,
    InstrumentScreeningResult,
    SQLiteFullUniverseScreeningStore,
    ScreeningDisposition,
    ScreeningEventType,
)

STATE_SCHEMA = "production-context-publication-state.v1"
STATE_FILENAME = "production-context-publication-state.json"
EXCLUSION_REASON = (
    "Certified candidate evidence is unavailable. The instrument remains monitored, "
    "but no recommendation is authorized."
)

ReadinessProbe = Callable[[FreePaperPilotUniverse], object]
CashProbe = Callable[[], object]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _state_path(settings: ApiSettings) -> Path:
    return settings.portfolio_database.parent / STATE_FILENAME


def _stamp(value: datetime) -> str:
    return _aware(value, field_name="decision_as_of").strftime("%Y%m%dT%H%M%S%fZ")


def _default_readiness_probe(universe: FreePaperPilotUniverse):
    client = create_alpaca_paper_client()
    return assess_free_paper_pilot_readiness(universe=universe, client=client)


def _default_cash_probe():
    return FREDProvider().get_latest_value("DGS10")


def _report_value(report: object, name: str, default=None):
    if isinstance(report, Mapping):
        return report.get(name, default)
    return getattr(report, name, default)


@dataclass(frozen=True, slots=True)
class ProductionContextPublicationResult:
    state: str
    cycle_key: str
    scheduled_for: datetime
    decision_as_of: datetime | None
    detail: str
    eligible_universe_identifier: str | None = None
    screening_publication_identifier: str | None = None
    context_identifier: str | None = None
    instrument_count: int = 0
    candidate_count: int = 0
    exclusion_count: int = 0
    paper_only: bool = True
    real_money_authorized: bool = False

    @property
    def ready(self) -> bool:
        return self.state in {"ready", "reused"}

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "cycle_key": self.cycle_key,
            "scheduled_for": self.scheduled_for.isoformat(),
            "decision_as_of": (
                None if self.decision_as_of is None else self.decision_as_of.isoformat()
            ),
            "detail": self.detail,
            "eligible_universe_identifier": self.eligible_universe_identifier,
            "screening_publication_identifier": self.screening_publication_identifier,
            "context_identifier": self.context_identifier,
            "instrument_count": self.instrument_count,
            "candidate_count": self.candidate_count,
            "exclusion_count": self.exclusion_count,
            "paper_only": True,
            "real_money_authorized": False,
        }


def _cycle_key(*, scheduled_for: datetime, timezone_name: str) -> str:
    local_date = scheduled_for.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    return f"canonical-cio:{timezone_name}:{local_date}"


def _resolved_state(
    *,
    settings: ApiSettings,
    cycle_key: str,
) -> dict[str, object] | None:
    state = _load_json(_state_path(settings))
    if (
        state is None
        or state.get("schema_version") != STATE_SCHEMA
        or state.get("cycle_key") != cycle_key
    ):
        return None
    return state


def _portfolio_at_decision(
    *,
    store: SQLiteCanonicalPortfolioStore,
    decision_as_of: datetime,
    context_identifier: str,
) -> CanonicalPortfolioSnapshot:
    store.verify_integrity()
    matches = tuple(
        item
        for item in store.history("COMPOUNDING", limit=10_000)
        if item.as_of == decision_as_of
    )
    if len(matches) > 1:
        raise RuntimeError(
            "multiple canonical portfolio snapshots exist at the publication timestamp"
        )
    if matches:
        snapshot = matches[0]
    else:
        latest = store.latest("COMPOUNDING")
        if latest is None:
            raise RuntimeError("canonical portfolio state is unavailable")
        if latest.as_of > decision_as_of:
            raise RuntimeError("canonical portfolio state is future-known")
        snapshot = replace(
            latest,
            identifier=f"portfolio:compounding:decision:{_stamp(decision_as_of)}",
            as_of=decision_as_of,
            source_identifiers=tuple(
                dict.fromkeys((*latest.source_identifiers, context_identifier))
            ),
        )
        store.append(snapshot)
    if snapshot.positions or snapshot.currency_balances:
        raise RuntimeError(
            "certified holding and cross-currency evidence is required before a "
            "non-cash portfolio can enter the production CIO cycle"
        )
    if snapshot.cash_amount <= 0.0:
        raise RuntimeError("canonical portfolio must retain positive cash")
    return snapshot


def _reuse_if_complete(
    *,
    settings: ApiSettings,
    state: Mapping[str, object],
    scheduled_for: datetime,
    cycle_key: str,
    instrument_count: int,
) -> ProductionContextPublicationResult | None:
    raw_decision = state.get("decision_as_of")
    if not isinstance(raw_decision, str):
        return None
    decision_as_of = _aware(
        datetime.fromisoformat(raw_decision),
        field_name="decision_as_of",
    )
    eligible_identifier = str(state.get("eligible_universe_identifier") or "")
    screening_identifier = str(state.get("screening_cycle_identifier") or "")
    context_identifier = str(state.get("context_identifier") or "")
    if not all((eligible_identifier, screening_identifier, context_identifier)):
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
    if (
        eligible_store.publication(eligible_identifier) is None
        or screening_store.publication(screening_identifier) is None
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
            "The certified paper-universe, complete exclusion screening, exact-time "
            "portfolio state, and production context were already persisted."
        ),
        eligible_universe_identifier=eligible_identifier,
        screening_publication_identifier=str(
            state.get("screening_publication_identifier") or ""
        ),
        context_identifier=context_identifier,
        instrument_count=instrument_count,
        candidate_count=0,
        exclusion_count=instrument_count,
    )


def _prepare_exclusion_only_production_context_for_cycle(
    *,
    settings: ApiSettings,
    scheduled_for: datetime,
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    readiness_probe: ReadinessProbe | None = None,
    cash_probe: CashProbe | None = None,
    clock: Clock | None = None,
) -> ProductionContextPublicationResult:
    """Persist a truthful no-candidate production package for one due paper cycle."""

    scheduled = _aware(scheduled_for, field_name="scheduled_for")
    cycle_key = _cycle_key(
        scheduled_for=scheduled,
        timezone_name=settings.scheduler_timezone,
    )
    universe = load_free_paper_pilot_universe(universe_path)
    existing_state = _resolved_state(settings=settings, cycle_key=cycle_key)
    if existing_state is not None:
        reused = _reuse_if_complete(
            settings=settings,
            state=existing_state,
            scheduled_for=scheduled,
            cycle_key=cycle_key,
            instrument_count=len(universe.instruments),
        )
        if reused is not None:
            return reused
        # A partial publication cannot safely absorb later provider evidence under
        # its original point-in-time boundary. Start a new immutable attempt.
        existing_state = None

    try:
        readiness = (readiness_probe or _default_readiness_probe)(universe)
    except Exception as error:
        return ProductionContextPublicationResult(
            state="blocked",
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=None,
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
        detail = (
            blockers[0]
            if blockers
            else "Alpaca paper assets and IEX quote coverage are incomplete."
        )
        return ProductionContextPublicationResult(
            state="blocked",
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=None,
            detail=detail,
            instrument_count=len(universe.instruments),
        )

    try:
        cash_observation = (cash_probe or _default_cash_probe)()
        cash_date = str(_report_value(cash_observation, "date", "")).strip()
        cash_value = float(_report_value(cash_observation, "value"))
        if not cash_date or not isfinite(cash_value):
            raise ValueError("cash observation is incomplete")
    except Exception as error:
        return ProductionContextPublicationResult(
            state="blocked",
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=None,
            detail=f"Certified cash-return evidence failed: {type(error).__name__}",
            instrument_count=len(universe.instruments),
        )

    quote_datetimes = tuple(
        _aware(
            datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")),
            field_name="quote_timestamp",
        )
        for _symbol, timestamp in quote_timestamps
    )
    now = _aware((clock or _utc_now)(), field_name="clock")
    if any(timestamp > now + timedelta(seconds=5) for timestamp in quote_datetimes):
        return ProductionContextPublicationResult(
            state="blocked",
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            decision_as_of=None,
            detail="Paper-universe quote evidence is future-known.",
            instrument_count=len(universe.instruments),
        )

    decision_as_of = now
    if decision_as_of < scheduled:
        return ProductionContextPublicationResult(
            state="blocked",
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
        return ProductionContextPublicationResult(
            state="blocked",
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
    catalog_identifier = f"catalog:{universe.identifier}"
    master_snapshot_identifier = f"alpaca-paper-assets:{stamp}"

    state_payload = {
        "schema_version": STATE_SCHEMA,
        "cycle_key": cycle_key,
        "scheduled_for": scheduled.isoformat(),
        "decision_as_of": decision_as_of.isoformat(),
        "eligible_universe_identifier": eligible_identifier,
        "screening_cycle_identifier": screening_cycle_identifier,
        "screening_publication_identifier": screening_publication_identifier,
        "context_identifier": context_identifier,
        "paper_only": True,
        "real_money_authorized": False,
    }
    _atomic_json(_state_path(settings), state_payload)

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

    _portfolio_at_decision(
        store=portfolio_store,
        decision_as_of=decision_as_of,
        context_identifier=context_identifier,
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
        ),
        model_versions=(
            ("eligible_universe_policy", universe.schema_version),
            ("candidate_admission", "certified-evidence-required.v1"),
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

    cash_expected_return = round(max(-1.0, min(1.0, cash_value / 100.0)), 8)
    opportunity_context = OpportunitySetContext(
        identifier=opportunity_identifier,
        as_of=decision_as_of,
        alternatives=(
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=cash_expected_return,
                implementation_cost_return=0.0,
                evidence_quality=0.95,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )
    queue = OpportunityEngine().build_queue((), opportunity_context)
    exclusions = tuple(
        InstrumentScreeningResult(
            cycle_identifier=screening_cycle_identifier,
            partition_index=0,
            instrument_identifier=item.instrument_identifier,
            symbol=item.symbol,
            disposition=ScreeningDisposition.EXCLUDED,
            completed_at=decision_as_of,
            reasons=(EXCLUSION_REASON,),
        )
        for item in universe.instruments
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
        candidate_count=0,
        excluded_count=len(universe.instruments),
        candidate_payloads=(),
        exclusions=tuple(item.to_dict() for item in exclusions),
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
        "metrics_provider": "ALPACA_PAPER_IEX",
        "candidate_provider": "CERTIFIED_EVIDENCE_ONLY",
        "catalog_identifier": catalog_identifier,
        "security_master_snapshot_identifier": master_snapshot_identifier,
        "universe_snapshot_identifier": eligible_identifier,
        "policy_version": universe.schema_version,
        "opportunity_context_identifier": opportunity_identifier,
        "eligible_instrument_count": len(universe.instruments),
        "structural_exclusion_count": 0,
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
                for item in exclusions
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
            candidate_evidence=(),
            holding_evidence=(),
        )
    )

    return ProductionContextPublicationResult(
        state="ready",
        cycle_key=cycle_key,
        scheduled_for=scheduled,
        decision_as_of=decision_as_of,
        detail=(
            "Certified the approved paper universe, recorded complete explicit "
            "exclusions for instruments without candidate evidence, and persisted "
            "an exact-time cash-only production context."
        ),
        eligible_universe_identifier=eligible_identifier,
        screening_publication_identifier=screening_publication_identifier,
        context_identifier=context_identifier,
        instrument_count=len(universe.instruments),
        candidate_count=0,
        exclusion_count=len(universe.instruments),
    )


def prepare_production_context_for_cycle(
    *,
    settings: ApiSettings,
    scheduled_for: datetime,
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    readiness_probe: ReadinessProbe | None = None,
    cash_probe: CashProbe | None = None,
    evidence_probe=None,
    equity_discovery_probe=None,
    clock: Clock | None = None,
) -> ProductionContextPublicationResult:
    """Publish decision-complete candidate and holding evidence for the paper cycle."""

    from production_context_publication_governed import (
        prepare_governed_production_context_for_cycle,
    )

    return prepare_governed_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        universe_path=universe_path,
        readiness_probe=readiness_probe,
        cash_probe=cash_probe,
        evidence_probe=evidence_probe,
        equity_discovery_probe=equity_discovery_probe,
        clock=clock,
    )


__all__ = [
    "ProductionContextPublicationResult",
    "prepare_production_context_for_cycle",
]
