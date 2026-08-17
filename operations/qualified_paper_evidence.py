"""Provider-free production probes for qualified paper evidence snapshots."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping

from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
from operations.evidence_collection_universe import build_evidence_collection_universe
from operations.evidence_state_scope import load_evidence_state_scope
from operations.paper_evidence_snapshot import (
    PaperEvidenceSnapshotError,
    load_paper_evidence_snapshot,
)

_SNAPSHOT_ENV = "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"


def production_snapshot_probe_enabled(values=None) -> bool:
    resolved = os.environ if values is None else values
    production = (
        str(resolved.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "")).strip().lower()
        == "production"
        or str(resolved.get("RENDER", "")).strip().lower() == "true"
    )
    return production and evidence_plane_enabled(resolved)


def _qualified_snapshot_for_cutoff(cutoff: datetime):
    """Reconstruct and load the evidence owner's exact immutable paper snapshot."""

    values = os.environ
    if not production_snapshot_probe_enabled(values):
        raise RuntimeError("qualified paper evidence probe is production-only")
    try:
        point_snapshot = ensure_point_in_time_snapshot(
            cutoff=cutoff,
            values=values,
            allow_refresh=False,
        )
        scope = load_evidence_state_scope(
            as_of=point_snapshot.plane_as_of,
            values=values,
        )
        universe, _holding_only = build_evidence_collection_universe(
            evidence_as_of=point_snapshot.plane_as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            values=values,
        )
        snapshot = load_paper_evidence_snapshot(
            evidence_as_of=point_snapshot.plane_as_of,
            universe=universe,
            values=values,
        )
    except (ContinuousEvidencePlaneError, PaperEvidenceSnapshotError) as error:
        raise RuntimeError(
            f"qualified paper evidence snapshot is not ready: {error}"
        ) from error
    values[_SNAPSHOT_ENV] = snapshot.snapshot_id
    return snapshot


def qualified_paper_readiness_probe(universe, *, cutoff: datetime | None = None):
    """Read broker/account/asset readiness acquired by the evidence owner."""

    snapshot = _qualified_snapshot_for_cutoff(cutoff or datetime.now(timezone.utc))
    provider_clock = snapshot.payload.get("provider_clock")
    if not isinstance(provider_clock, Mapping):
        raise RuntimeError("qualified paper readiness metadata is unavailable")
    readiness = provider_clock.get("paper_readiness")
    if not isinstance(readiness, Mapping):
        raise RuntimeError("qualified paper readiness metadata is unavailable")
    if str(readiness.get("universe_identifier") or "") != str(universe.identifier):
        raise RuntimeError("qualified paper readiness universe changed")
    return dict(readiness)


def qualified_cash_probe(*, cutoff: datetime | None = None):
    """Read the qualified DGS10 cash-return observation without FRED acquisition."""

    snapshot = _qualified_snapshot_for_cutoff(cutoff or datetime.now(timezone.utc))
    macro = snapshot.payload.get("macro")
    if not isinstance(macro, Mapping) or "DGS10" not in macro:
        raise RuntimeError("qualified DGS10 cash-return evidence is unavailable")
    return macro["DGS10"]


def qualified_paper_evidence_probe(universe, decision_as_of):
    """Load the exact qualified raw-evidence handoff without provider acquisition."""

    values = os.environ
    if not production_snapshot_probe_enabled(values):
        raise RuntimeError("qualified paper evidence probe is production-only")
    try:
        point_snapshot = ensure_point_in_time_snapshot(
            cutoff=decision_as_of,
            values=values,
            allow_refresh=False,
        )
        snapshot = load_paper_evidence_snapshot(
            evidence_as_of=point_snapshot.plane_as_of,
            universe=universe,
            values=values,
        )
    except (ContinuousEvidencePlaneError, PaperEvidenceSnapshotError) as error:
        raise RuntimeError(
            f"qualified paper evidence snapshot is not ready: {error}"
        ) from error
    values[_SNAPSHOT_ENV] = snapshot.snapshot_id
    return snapshot.payload


__all__ = [
    "production_snapshot_probe_enabled",
    "qualified_cash_probe",
    "qualified_paper_evidence_probe",
    "qualified_paper_readiness_probe",
]
