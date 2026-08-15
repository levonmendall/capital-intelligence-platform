"""Lossless qualified-runtime view of immutable global discovery snapshots.

The base snapshot module owns persistence and integrity.  This adapter restores the
provider-preselection evidence and continuity metadata required by the current qualified
comprehensive-discovery runtime and compositional lane certification.  It performs no
provider acquisition and has no investment or execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4_serial as _qualified
from operations import comprehensive_discovery_snapshot as _snapshot


ComprehensiveDiscoverySnapshotError = _snapshot.ComprehensiveDiscoverySnapshotError


class QualifiedComprehensiveDiscoverySnapshot(_snapshot.ComprehensiveDiscoverySnapshot):
    """Type marker for a snapshot restored with qualified lane metadata."""


def _restore_preselection_evidence(
    payload: Mapping[str, object],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    raw = payload.get("preselection_evidence", [])
    if not isinstance(raw, list):
        raise ComprehensiveDiscoverySnapshotError(
            "snapshot preselection evidence is invalid"
        )
    restored: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ComprehensiveDiscoverySnapshotError(
                "snapshot preselection evidence entry is invalid"
            )
        symbol = str(item[0]).strip().upper()
        identifiers = item[1]
        if (
            not symbol
            or symbol in seen
            or not isinstance(identifiers, list)
            or any(not str(identifier).strip() for identifier in identifiers)
        ):
            raise ComprehensiveDiscoverySnapshotError(
                "snapshot preselection evidence entry is malformed"
            )
        seen.add(symbol)
        restored.append(
            (symbol, tuple(str(identifier) for identifier in identifiers))
        )
    return tuple(restored)


def _restore_lane(payload: Mapping[str, object]) -> _qualified.DiscoveryLaneResult:
    raw_selected = payload.get("selected")
    raw_exclusions = payload.get("exclusions")
    raw_sources = payload.get("source_identifiers")
    if (
        not isinstance(raw_selected, list)
        or not isinstance(raw_exclusions, list)
        or not isinstance(raw_sources, list)
    ):
        raise ComprehensiveDiscoverySnapshotError("snapshot lane collections are invalid")

    selected = []
    for item in raw_selected:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("catalog"), Mapping)
            or not isinstance(item.get("features"), Mapping)
        ):
            raise ComprehensiveDiscoverySnapshotError(
                "snapshot selected instrument is invalid"
            )
        selected.append(
            _qualified.DiscoveredMarketInstrument(
                catalog=_snapshot._restore_catalog(item["catalog"]),
                features=_snapshot._restore_features(item["features"]),
                retained_for_state=bool(item.get("retained_for_state", False)),
            )
        )

    exclusions: list[tuple[str, str]] = []
    for item in raw_exclusions:
        if not isinstance(item, list) or len(item) != 2:
            raise ComprehensiveDiscoverySnapshotError("snapshot exclusion is invalid")
        exclusions.append((str(item[0]), str(item[1])))

    try:
        return _qualified.DiscoveryLaneResult(
            asset_class=CandidateAssetClass(str(payload["asset_class"])),
            catalog_count=int(payload["catalog_count"]),
            deep_analyzed_count=int(payload["deep_analyzed_count"]),
            selected=tuple(selected),
            exclusions=tuple(exclusions),
            source_identifiers=tuple(str(item) for item in raw_sources),
            scheduled=bool(payload.get("scheduled", True)),
            schedule_reason=(
                None
                if payload.get("schedule_reason") in (None, "")
                else str(payload["schedule_reason"])
            ),
            continuity_count=int(payload.get("continuity_count", 0)),
            preselection=None,
            preselection_evidence=_restore_preselection_evidence(payload),
            cutoff_observations=(),
            cutoff_outcomes=(),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ComprehensiveDiscoverySnapshotError("snapshot lane is invalid") from error


def load_qualified_comprehensive_discovery_snapshot(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str] | None = None,
) -> QualifiedComprehensiveDiscoverySnapshot:
    """Restore the exact evidence-cutoff snapshot with qualified lane lineage."""

    resolved = dict(_snapshot.os.environ if values is None else values)
    expected_as_of = _snapshot._aware(evidence_as_of, field_name="evidence_as_of")
    root = _snapshot._root(resolved)
    pointer = _snapshot._read_pointer(
        root / "by-as-of" / f"{_snapshot._stamp(expected_as_of)}.json"
    )
    if pointer.get("schema_version") != _snapshot._POINTER_SCHEMA:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot pointer schema is invalid"
        )
    if pointer.get("as_of") != expected_as_of.isoformat():
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot cutoff mismatch"
        )
    snapshot_id = str(pointer.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot identifier is missing"
        )
    payload = _snapshot._read_snapshot(
        root / "snapshots" / f"{snapshot_id}.json",
        expected_id=snapshot_id,
    )
    if payload.get("as_of") != expected_as_of.isoformat():
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot evidence cutoff changed"
        )

    state_scope = payload.get("state_scope")
    if not isinstance(state_scope, Mapping):
        raise ComprehensiveDiscoverySnapshotError("snapshot state scope is invalid")
    held_raw = state_scope.get("held_symbols")
    tracked_raw = state_scope.get("tracked_symbols")
    if not isinstance(held_raw, list) or not isinstance(tracked_raw, list):
        raise ComprehensiveDiscoverySnapshotError("snapshot state scope is malformed")
    held = _snapshot._symbols(tuple(str(item) for item in held_raw))
    tracked = _snapshot._symbols(tuple(str(item) for item in tracked_raw))
    if list(held) != held_raw or list(tracked) != tracked_raw:
        raise ComprehensiveDiscoverySnapshotError(
            "snapshot state scope is not canonical"
        )

    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, list):
        raise ComprehensiveDiscoverySnapshotError("snapshot lanes are invalid")
    lanes = tuple(
        _restore_lane(item)
        for item in raw_lanes
        if isinstance(item, Mapping)
    )
    if len(lanes) != len(raw_lanes):
        raise ComprehensiveDiscoverySnapshotError("snapshot contains an invalid lane")

    result = _qualified.ComprehensiveMarketDiscoveryResult(
        identifier=str(payload.get("identifier") or ""),
        as_of=expected_as_of,
        policy_version=str(payload.get("policy_version") or ""),
        lanes=lanes,
        manifest_fingerprint=str(payload.get("manifest_fingerprint") or ""),
    )
    if not result.identifier or not result.policy_version or not result.manifest_fingerprint:
        raise ComprehensiveDiscoverySnapshotError(
            "snapshot discovery identity is incomplete"
        )
    return QualifiedComprehensiveDiscoverySnapshot(
        snapshot_id=snapshot_id,
        evidence_as_of=expected_as_of,
        held_symbols=held,
        tracked_symbols=tracked,
        result=result,
    )


def view_qualified_comprehensive_discovery_snapshot(
    snapshot: QualifiedComprehensiveDiscoverySnapshot,
    *,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
) -> _qualified.ComprehensiveMarketDiscoveryResult:
    """Apply only local exclusions after proving continuity-scope compatibility."""

    held = _snapshot._symbols(held_symbols)
    tracked = _snapshot._symbols(tracked_symbols)
    if held != snapshot.held_symbols or tracked != snapshot.tracked_symbols:
        raise ComprehensiveDiscoverySnapshotError(
            "comprehensive discovery snapshot state scope does not match current portfolio/learning state"
        )
    excluded = frozenset(_snapshot._symbols(excluded_symbols))
    if not excluded:
        return snapshot.result

    lanes: list[_qualified.DiscoveryLaneResult] = []
    for lane in snapshot.result.lanes:
        removed = tuple(
            item for item in lane.selected if item.catalog.symbol in excluded
        )
        selected = tuple(
            item for item in lane.selected if item.catalog.symbol not in excluded
        )
        exclusions = tuple(
            (
                *lane.exclusions,
                *(
                    (item.catalog.symbol, "explicit_discovery_exclusion")
                    for item in removed
                ),
            )
        )
        lanes.append(
            _qualified.DiscoveryLaneResult(
                asset_class=lane.asset_class,
                catalog_count=lane.catalog_count,
                deep_analyzed_count=lane.deep_analyzed_count,
                selected=selected,
                exclusions=exclusions,
                source_identifiers=lane.source_identifiers,
                scheduled=lane.scheduled,
                schedule_reason=lane.schedule_reason,
                continuity_count=lane.continuity_count,
                preselection=None,
                preselection_evidence=lane.preselection_evidence,
                cutoff_observations=(),
                cutoff_outcomes=(),
            )
        )

    view_material = {
        "source_snapshot_id": snapshot.snapshot_id,
        "source_manifest_fingerprint": snapshot.result.manifest_fingerprint,
        "excluded_symbols": sorted(excluded),
    }
    view_id = _snapshot._digest(view_material)
    return _qualified.ComprehensiveMarketDiscoveryResult(
        identifier=f"{snapshot.result.identifier}:consumer-view:{view_id[:16]}",
        as_of=snapshot.result.as_of,
        policy_version=snapshot.result.policy_version,
        lanes=tuple(lanes),
        manifest_fingerprint=view_id,
    )


__all__ = [
    "ComprehensiveDiscoverySnapshotError",
    "QualifiedComprehensiveDiscoverySnapshot",
    "load_qualified_comprehensive_discovery_snapshot",
    "view_qualified_comprehensive_discovery_snapshot",
]
