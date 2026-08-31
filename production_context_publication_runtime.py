"""Canonical production-context publication runtime surface.

The governed publisher owns production-context construction. This module retains the
shared compatibility helpers consumed by that publisher and provides the single public
entrypoint used by production callers. Broker readiness, cash evidence, market evidence,
and dynamic candidates default to provider-free qualified consumers in production;
explicit probes remain available for tests and rehearsals.

After a governed publication is complete, this runtime also reconciles its exact active
universe through the Universal Capability Graph and append-only instrument paper-
eligibility authority before the CIO can consume the publication.

On Render the canonical operating path is capability-scoped by default. Comprehensive
all-market discovery remains an independent certification/coverage process. The CIO uses
only exact current capability-authorized instruments that are also present in the fresh
independent operating-evidence snapshot. A failure in unrelated discovery therefore cannot
prevent independently qualified instruments from reaching the governed CIO.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from api.config import ApiSettings
from operations.certification_runtime_state import advance_linear_state_for_cutoff
from operations.certification_state_machine import CertificationState
from operations.evidence_file_cache_release import (
    release_completed_operating_evidence_file_cache,
)
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    FreePaperPilotUniverse,
    assess_free_paper_pilot_readiness,
    weekday_market_evaluation_scheduled,
)
from operations.production_capability_authority import (
    reconcile_production_capability_authority,
)
from operations.shadow_opportunity_ledger import (
    record_capability_blocked_opportunities,
)
from production_context_screening_resource_guard import (
    ensure_screening_headroom,
    trim_released_heap,
)
from providers.alpaca_paper import create_alpaca_paper_client
from providers.fred import FREDProvider

STATE_SCHEMA = "production-context-publication-state.v1"
STATE_FILENAME = "production-context-publication-state.json"
CAPABILITY_REPORT_FILENAME = "production-capability-authority.json"
SHADOW_OPPORTUNITY_DATABASE_FILENAME = "shadow-opportunity-ledger.db"

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


def _capability_scoped_operation_enabled() -> bool:
    """Return whether the normal production CIO should avoid global atomic discovery.

    An explicit environment setting wins. Render defaults to the capability-scoped
    runtime because all-market certification has its own diagnostic/background path.
    Tests and local rehearsals retain the historical full-discovery behavior unless
    they opt in explicitly.
    """

    raw = os.getenv("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("RENDER", "").strip().lower() == "true"


def _screening_resource_progress_probe(
    progress_probe: Callable[[str], None] | None,
) -> Callable[[str], None]:
    """Protect the expensive screening stream without changing screening semantics.

    The governed publisher has already deleted the large discovery graph when it emits
    ``production_context_screening_graph_released``. At that exact handoff, release both
    already-unreferenced heap arenas and clean file-cache pages belonging to the qualified
    operating-evidence epoch that the context build has just consumed. The existing
    ``production_context_screening_start_persisted`` event is forwarded before the guard
    runs so a low-headroom stop remains durable and attributable to the exact boundary.
    """

    def guarded(stage: str) -> None:
        if stage == "production_context_screening_graph_released":
            trim_released_heap()
            release_completed_operating_evidence_file_cache(os.environ)
        if progress_probe is not None:
            progress_probe(stage)
        if stage == "production_context_screening_start_persisted":
            ensure_screening_headroom()

    return guarded


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
    qualified_candidate_count: int = 0
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
            "decision_as_of": None if self.decision_as_of is None else self.decision_as_of.isoformat(),
            "detail": self.detail,
            "eligible_universe_identifier": self.eligible_universe_identifier,
            "screening_publication_identifier": self.screening_publication_identifier,
            "context_identifier": self.context_identifier,
            "instrument_count": self.instrument_count,
            "candidate_count": self.candidate_count,
            "qualified_candidate_count": self.qualified_candidate_count,
            "exclusion_count": self.exclusion_count,
            "paper_only": True,
            "real_money_authorized": False,
        }


def _cycle_key(*, scheduled_for: datetime, timezone_name: str) -> str:
    local_date = scheduled_for.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    return f"canonical-cio:{timezone_name}:{local_date}"


def _advance_screening_if_ready(result: ProductionContextPublicationResult) -> None:
    if not result.ready:
        return
    if result.decision_as_of is None:
        raise RuntimeError("ready production context is missing decision_as_of")
    source = str(result.screening_publication_identifier or "").strip()
    if not source:
        raise RuntimeError("ready production context is missing screening publication identity")
    advance_linear_state_for_cutoff(
        cutoff=result.decision_as_of,
        target=CertificationState.SCREENING_COMPLETE,
        source_id=source,
        detail="canonical full-universe screening publication persisted",
        metadata={
            "cycle_key": result.cycle_key,
            "context_identifier": result.context_identifier,
            "eligible_universe_identifier": result.eligible_universe_identifier,
            "candidate_count": result.candidate_count,
            "qualified_candidate_count": result.qualified_candidate_count,
            "exclusion_count": result.exclusion_count,
        },
    )


def _shadow_learning_payload(
    *,
    settings: ApiSettings,
    report: object,
    publication_identifier: str,
    screening_cycle_identifier: str,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Persist non-authoritative observations without blocking canonical operation."""

    database_path = (
        settings.portfolio_database.parent / SHADOW_OPPORTUNITY_DATABASE_FILENAME
    )
    transitions = tuple(getattr(report, "transitions", ()) or ())
    try:
        recorded = record_capability_blocked_opportunities(
            database_path=database_path,
            publication_identifier=publication_identifier,
            screening_cycle_identifier=screening_cycle_identifier,
            observed_at=evaluated_at,
            transitions=transitions,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        return {
            "state": "degraded",
            "detail": f"shadow opportunity learning failed: {type(error).__name__}",
            "database_path": str(database_path),
            "recorded_count": 0,
            "canonical_execution_authority": False,
            "real_money_authorized": False,
        }
    return {
        "state": "recorded",
        "database_path": str(database_path),
        "recorded_count": len(recorded),
        "canonical_execution_authority": False,
        "real_money_authorized": False,
    }


def _reconcile_capability_authority_if_ready(
    *,
    settings: ApiSettings,
    result: ProductionContextPublicationResult,
) -> None:
    if not result.ready:
        return
    if result.decision_as_of is None:
        raise RuntimeError("ready production context is missing decision_as_of")
    eligible_identifier = str(result.eligible_universe_identifier or "").strip()
    if not eligible_identifier:
        raise RuntimeError("ready production context is missing eligible-universe identity")
    state_path = _state_path(settings)
    state = _load_json(state_path)
    if not isinstance(state, dict):
        raise RuntimeError("production publication state is unavailable for capability authority")
    screening_cycle_identifier = str(
        state.get("screening_cycle_identifier", "")
    ).strip()
    if not screening_cycle_identifier:
        raise RuntimeError("production publication state lacks screening cycle identity")
    report = reconcile_production_capability_authority(
        settings=settings,
        publication_identifier=eligible_identifier,
        screening_cycle_identifier=screening_cycle_identifier,
        evaluated_at=result.decision_as_of,
    )
    payload = report.to_dict()
    payload["operating_scope"] = (
        "capability_scoped"
        if _capability_scoped_operation_enabled()
        else "comprehensive_discovery"
    )
    payload["all_market_certification_is_operating_gate"] = False
    payload["shadow_opportunity_learning"] = _shadow_learning_payload(
        settings=settings,
        report=report,
        publication_identifier=eligible_identifier,
        screening_cycle_identifier=screening_cycle_identifier,
        evaluated_at=result.decision_as_of,
    )
    _atomic_json(
        settings.portfolio_database.parent / CAPABILITY_REPORT_FILENAME,
        payload,
    )
    state["production_capability_authority"] = payload
    _atomic_json(state_path, state)


def _stable_production_snapshot_clock() -> Clock:
    frozen: datetime | None = None

    def clock() -> datetime:
        nonlocal frozen
        if frozen is None:
            frozen = _utc_now()
        return frozen

    return clock


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
    progress_probe: Callable[[str], None] | None = None,
) -> ProductionContextPublicationResult:
    """Publish one governed context from the currently legitimate operating scope."""

    from production_context_publication_governed import prepare_governed_production_context_for_cycle

    capability_scoped = _capability_scoped_operation_enabled()
    if equity_discovery_probe is None:
        if capability_scoped:
            from operations.capability_scoped_discovery import (
                discover_currently_certified_us_equities,
            )

            equity_discovery_probe = discover_currently_certified_us_equities
        else:
            from operations.qualified_equity_discovery import (
                discover_us_equities as qualified_equity_discovery_probe,
            )

            equity_discovery_probe = qualified_equity_discovery_probe

    if evidence_probe is None:
        from operations.qualified_paper_evidence import (
            production_snapshot_probe_enabled,
            qualified_cash_probe,
            qualified_paper_evidence_probe,
            qualified_paper_readiness_probe,
        )
        snapshot_probe_active = production_snapshot_probe_enabled()
        if snapshot_probe_active:
            if clock is None:
                clock = _stable_production_snapshot_clock()
            evidence_probe = qualified_paper_evidence_probe
            if readiness_probe is None and weekday_market_evaluation_scheduled(scheduled_for):
                readiness_probe = lambda universe: qualified_paper_readiness_probe(universe, cutoff=clock())
            if cash_probe is None:
                cash_probe = lambda: qualified_cash_probe(cutoff=clock())

    comprehensive_discovery_probe = None
    comprehensive_discovery_required = None
    if capability_scoped:
        from operations.capability_scoped_discovery import (
            discover_currently_certified_capabilities,
        )

        comprehensive_discovery_probe = discover_currently_certified_capabilities
        comprehensive_discovery_required = False

    result = prepare_governed_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        universe_path=universe_path,
        readiness_probe=readiness_probe,
        cash_probe=cash_probe,
        evidence_probe=evidence_probe,
        equity_discovery_probe=equity_discovery_probe,
        comprehensive_discovery_probe=comprehensive_discovery_probe,
        comprehensive_discovery_required=comprehensive_discovery_required,
        clock=clock,
        progress_probe=_screening_resource_progress_probe(progress_probe),
    )
    _advance_screening_if_ready(result)
    _reconcile_capability_authority_if_ready(settings=settings, result=result)
    return result


__all__ = [
    "ProductionContextPublicationResult",
    "prepare_production_context_for_cycle",
]
