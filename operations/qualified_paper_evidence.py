"""Provider-free production probe for qualified paper evidence snapshots."""

from __future__ import annotations

import os

from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
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
    "qualified_paper_evidence_probe",
]
