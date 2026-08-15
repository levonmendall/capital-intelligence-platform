"""Canonical production-context publication runtime surface.

The governed publisher owns production-context construction. This module retains the
shared compatibility helpers consumed by that publisher and provides the single public
entrypoint used by production callers. Broad discovery and heavy paper evidence default
to provider-free qualified snapshot consumers in production; explicit probes remain
available for tests and rehearsals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from api.config import ApiSettings
from operations.certification_runtime_state import advance_linear_state_for_cutoff
from operations.certification_state_machine import CertificationState
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    FreePaperPilotUniverse,
    assess_free_paper_pilot_readiness,
)
from providers.alpaca_paper import create_alpaca_paper_client
from providers.fred import FREDProvider

STATE_SCHEMA = "production-context-publication-state.v1"
STATE_FILENAME = "production-context-publication-state.json"

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
            "decision_as_of": (
                None if self.decision_as_of is None else self.decision_as_of.isoformat()
            ),
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
    """Bind a persisted full-universe screening publication to its exact input cutoff."""

    if not result.ready:
        return
    if result.decision_as_of is None:
        raise RuntimeError("ready production context is missing decision_as_of")
    source = str(result.screening_publication_identifier or "").strip()
    if not source:
        raise RuntimeError(
            "ready production context is missing screening publication identity"
        )
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
    """Publish one governed context using already-qualified evidence in production."""

    from production_context_publication_governed import (
        prepare_governed_production_context_for_cycle,
    )

    if equity_discovery_probe is None:
        from operations.qualified_equity_discovery import (
            discover_us_equities as qualified_equity_discovery_probe,
        )

        equity_discovery_probe = qualified_equity_discovery_probe

    if evidence_probe is None:
        from operations.qualified_paper_evidence import (
            production_snapshot_probe_enabled,
            qualified_paper_evidence_probe,
        )

        if production_snapshot_probe_enabled():
            evidence_probe = qualified_paper_evidence_probe

    result = prepare_governed_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        universe_path=universe_path,
        readiness_probe=readiness_probe,
        cash_probe=cash_probe,
        evidence_probe=evidence_probe,
        equity_discovery_probe=equity_discovery_probe,
        clock=clock,
    )
    _advance_screening_if_ready(result)
    return result


__all__ = [
    "ProductionContextPublicationResult",
    "prepare_production_context_for_cycle",
]
