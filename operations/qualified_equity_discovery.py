"""Provider-free production consumer for broad U.S.-equity discovery evidence."""

from __future__ import annotations

import os
from typing import Sequence

from operations import equity_discovery as _core
from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
from operations.equity_discovery import *  # noqa: F401,F403
from operations.equity_discovery_snapshot import (
    EquityDiscoverySnapshotError,
    load_equity_discovery_snapshot,
    view_equity_discovery_snapshot,
)

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_SNAPSHOT_ENV = "CAPITAL_INTELLIGENCE_CIO_US_EQUITY_DISCOVERY_SNAPSHOT_ID"


def _production_plane_enabled(values) -> bool:
    explicit = values.get(
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", ""
    ).strip()
    production = (
        values.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "").strip().lower()
        == "production"
        or values.get("RENDER", "").strip().lower() == "true"
    )
    return (bool(explicit) or production) and evidence_plane_enabled(values)


def discover_us_equities(
    *,
    as_of,
    held_symbols: Sequence[str] = (),
    tracked_symbols: Sequence[str] = (),
    excluded_symbols: Sequence[str] = (),
    client=None,
    sec_provider=None,
    policy=None,
):
    """Consume exact qualified evidence in production; acquire only as evidence owner."""

    values = os.environ
    is_production_consumer = _production_plane_enabled(values) and values.get(
        _PREPARING_ENV, ""
    ).strip().lower() not in {"1", "true", "yes", "on"}
    if not is_production_consumer:
        return _core.discover_us_equities(
            as_of=as_of,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=excluded_symbols,
            client=client,
            sec_provider=sec_provider,
            policy=policy,
        )

    if client is not None or sec_provider is not None or policy is not None:
        raise RuntimeError(
            "production U.S.-equity consumer cannot override qualified evidence"
        )

    try:
        point_snapshot = ensure_point_in_time_snapshot(
            cutoff=as_of,
            values=values,
            allow_refresh=False,
        )
        snapshot = load_equity_discovery_snapshot(
            evidence_as_of=point_snapshot.plane_as_of,
            values=values,
        )
        result = view_equity_discovery_snapshot(
            snapshot,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=excluded_symbols,
        )
    except (ContinuousEvidencePlaneError, EquityDiscoverySnapshotError) as error:
        raise RuntimeError(
            f"qualified U.S.-equity discovery snapshot is not ready: {error}"
        ) from error
    values[_SNAPSHOT_ENV] = snapshot.snapshot_id
    return result


__all__ = tuple(
    dict.fromkeys(
        (
            *_core.__all__,
            "discover_us_equities",
        )
    )
)
