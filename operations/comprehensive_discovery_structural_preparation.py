"""Prepare slow reference-catalog structure before the fresh all-market evidence epoch.

Comprehensive discovery has two materially different kinds of work.  Release-qualified
reference catalogs are slow-changing structural inputs with their own governed freshness
contract, while provider-preselection factors, option pricing/history, terminal screening,
and deep market evidence are decision-time evidence.  Serializing every market lane made
that distinction operationally important: rebuilding large reference catalogs inside the
900-second decision-evidence epoch can consume the entire freshness budget before current
market evidence is even collected.

This module persists only the reference-catalog object shards that are already authorized
by the exact bound reference manifest.  It never calls option discovery, provider
preselection, terminal screening, or a market-evidence probe.  The stage-isolated evidence
worker validates this structural manifest and only then starts a new evidence epoch.  The
fresh comprehensive-discovery stage may consume these shards, but all freshness-sensitive
work remains exact-epoch and fail-closed.

The artifacts are operational transport only.  They have no investment, candidate,
sizing, construction, execution, evidence-certification, freshness-epoch, or real-money
authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from cio import CandidateAssetClass
from operations import comprehensive_discovery_input_spool as _spool


_SCHEMA_VERSION = "comprehensive-discovery-structural-preparation.v1"
_MANIFEST_ENV = "CAPITAL_INTELLIGENCE_COMPREHENSIVE_STRUCTURAL_MANIFEST_PATH"
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_REFERENCE_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"


@dataclass(frozen=True, slots=True)
class StructuralPreparationManifest:
    manifest_id: str
    path: Path
    reference_manifest_id: str
    prepared_as_of: datetime
    completed_at: datetime
    scheduled_lanes: tuple[str, ...]
    reference_lanes: tuple[str, ...]
    record_count: int


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise _spool.ComprehensiveDiscoverySpoolError(
            f"structural preparation {field_name} is invalid"
        ) from error
    return _aware(parsed, field_name=field_name)


def _reference_lane_set() -> frozenset[CandidateAssetClass]:
    from operations import generalized_reference_readiness as generalized

    return frozenset((*generalized._EODHD_REFERENCE_LANES, CandidateAssetClass.FUTURE))


def _active_lanes(timestamp: datetime) -> tuple[CandidateAssetClass, ...]:
    from operations import comprehensive_market_discovery as facade

    active = facade._core._base.scheduled_discovery_lanes(timestamp)
    return tuple(sorted(active, key=lambda item: item.value))


def _active_reference_lanes(timestamp: datetime) -> tuple[CandidateAssetClass, ...]:
    reference = _reference_lane_set()
    return tuple(item for item in _active_lanes(timestamp) if item in reference)


def _compatibility_id(
    *,
    release: str,
    reference_manifest_id: str,
    scheduled_lanes: Sequence[CandidateAssetClass],
) -> str:
    return _spool._digest(
        {
            "schema_version": _SCHEMA_VERSION,
            "release": release,
            "reference_manifest_id": reference_manifest_id,
            "scheduled_lanes": [item.value for item in scheduled_lanes],
        }
    )


def _root(values: Mapping[str, str]) -> Path:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not raw:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for structural preparation"
        )
    release = _spool._release(values)
    if not release or release == "unknown":
        raise _spool.ComprehensiveDiscoverySpoolError(
            "exact release identity is required for structural preparation"
        )
    return (
        Path(raw).expanduser()
        / "comprehensive-discovery-structural"
        / _spool._safe_release(release)
    )


def _manifest_path(
    values: Mapping[str, str],
    *,
    reference_manifest_id: str,
    scheduled_lanes: Sequence[CandidateAssetClass],
) -> Path:
    compatibility = _compatibility_id(
        release=_spool._release(values),
        reference_manifest_id=reference_manifest_id,
        scheduled_lanes=scheduled_lanes,
    )
    return _root(values) / compatibility / "manifest.json"


def _authority_fields() -> dict[str, object]:
    return {
        "structural_only": True,
        "market_evidence_included": False,
        "option_evidence_included": False,
        "provider_preselection_included": False,
        "terminal_screening_included": False,
        "evidence_certified": False,
        "freshness_epoch_authority": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _validate_authority(body: Mapping[str, object]) -> None:
    expected = _authority_fields()
    if any(body.get(key) is not value for key, value in expected.items()):
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation authority boundary is invalid"
        )


def _manifest_from_body(
    path: Path,
    body: Mapping[str, object],
    *,
    verify_blobs: bool,
) -> StructuralPreparationManifest:
    _validate_authority(body)
    material = dict(body)
    manifest_id = str(material.pop("manifest_id", "") or "").strip()
    if not manifest_id or manifest_id != _spool._digest(material):
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation manifest identity mismatch"
        )
    lanes_raw = body.get("lanes")
    if not isinstance(lanes_raw, list):
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation lane descriptors are malformed"
        )
    record_count = 0
    seen: set[str] = set()
    for item in lanes_raw:
        if not isinstance(item, Mapping):
            raise _spool.ComprehensiveDiscoverySpoolError(
                "structural preparation lane descriptor is malformed"
            )
        lane = str(item.get("asset_class") or "").strip()
        if not lane or lane in seen:
            raise _spool.ComprehensiveDiscoverySpoolError(
                "structural preparation lane identity is invalid"
            )
        seen.add(lane)
        descriptor = _spool._descriptor(item.get("blob"))
        if verify_blobs:
            _spool._verify_blob(path.parent, descriptor)
        try:
            count = int(item.get("record_count", -1))
        except (TypeError, ValueError) as error:
            raise _spool.ComprehensiveDiscoverySpoolError(
                "structural preparation record count is malformed"
            ) from error
        if count < 0:
            raise _spool.ComprehensiveDiscoverySpoolError(
                "structural preparation record count is invalid"
            )
        record_count += count
    scheduled_raw = body.get("scheduled_lanes")
    reference_raw = body.get("reference_lanes")
    if not isinstance(scheduled_raw, list) or not isinstance(reference_raw, list):
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation lane scope is malformed"
        )
    scheduled = tuple(str(item) for item in scheduled_raw)
    reference = tuple(str(item) for item in reference_raw)
    if tuple(sorted(scheduled)) != scheduled or tuple(sorted(reference)) != reference:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation lane scope is not canonical"
        )
    if tuple(sorted(seen)) != reference:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation reference lane set changed"
        )
    if int(body.get("record_count", -1)) != record_count:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation aggregate record count changed"
        )
    return StructuralPreparationManifest(
        manifest_id=manifest_id,
        path=path,
        reference_manifest_id=str(body.get("reference_manifest_id") or ""),
        prepared_as_of=_parse_timestamp(body.get("prepared_as_of"), field_name="prepared_as_of"),
        completed_at=_parse_timestamp(body.get("completed_at"), field_name="completed_at"),
        scheduled_lanes=scheduled,
        reference_lanes=reference,
        record_count=record_count,
    )


def load_structural_manifest(
    path: str | Path,
    *,
    values: Mapping[str, str],
    reference_manifest_id: str,
    exact_as_of: datetime,
    verify_blobs: bool = True,
) -> StructuralPreparationManifest:
    manifest_path = Path(path).expanduser()
    body = _spool._load_json(manifest_path, schema=_SCHEMA_VERSION)
    if str(body.get("release") or "") != _spool._release(values):
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation release does not match runtime"
        )
    if str(body.get("reference_manifest_id") or "") != reference_manifest_id:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation reference binding changed"
        )
    exact_active = tuple(item.value for item in _active_lanes(_aware(exact_as_of, field_name="exact_as_of")))
    if tuple(body.get("scheduled_lanes") or ()) != exact_active:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation scheduled-lane scope changed before fresh evidence epoch"
        )
    return _manifest_from_body(manifest_path, body, verify_blobs=verify_blobs)


def _load_reference_lane_records(
    *,
    values: Mapping[str, str],
    timestamp: datetime,
    asset_class: CandidateAssetClass,
) -> tuple[object, ...]:
    from operations import comprehensive_market_discovery as facade
    from operations import supervised_reference_prequalification as supervised
    from operations import lane_local_comprehensive_discovery_spool as lane_local

    core = facade._core
    config = core._base.load_comprehensive_market_discovery_config()
    component = supervised._load_asset_component(
        values,
        discovery=core,
        config=config,
        lane=asset_class,
        timestamp=timestamp,
    )
    if component is None:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "qualified lane-scoped reference component is unavailable for structural preparation; "
            f"lane={asset_class.value}"
        )
    return lane_local._reconstruct_component_records(
        component,
        record_type=core._base._legacy.DiscoveryCatalogRecord,
    )


def prepare_structural_reference_catalogs(
    values: Mapping[str, str],
    *,
    reference_manifest_id: str,
    preparation_as_of: datetime | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> StructuralPreparationManifest:
    """Freeze only release-qualified reference catalogs before starting the fresh epoch."""

    reference_id = str(reference_manifest_id or "").strip()
    if not reference_id:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "structural preparation requires an exact reference manifest identity"
        )
    timestamp = _aware(
        datetime.now(timezone.utc) if preparation_as_of is None else preparation_as_of,
        field_name="preparation_as_of",
    )
    active = _active_lanes(timestamp)
    reference_lanes = tuple(item for item in active if item in _reference_lane_set())
    path = _manifest_path(
        values,
        reference_manifest_id=reference_id,
        scheduled_lanes=active,
    )
    if path.exists():
        return load_structural_manifest(
            path,
            values=values,
            reference_manifest_id=reference_id,
            exact_as_of=timestamp,
        )

    directory = path.parent
    lanes: list[dict[str, object]] = []
    total_records = 0
    total_lanes = len(reference_lanes)
    for index, asset_class in enumerate(reference_lanes):
        if progress_callback is not None:
            progress_callback(asset_class.value, index, total_lanes)
        records = _load_reference_lane_records(
            values=values,
            timestamp=timestamp,
            asset_class=asset_class,
        )
        descriptor = _spool._write_pickle_blob(
            directory,
            f"reference-catalog-{index:03d}-{_spool._safe_release(asset_class.value)}.pkl",
            records,
        )
        count = len(records)
        total_records += count
        lanes.append(
            {
                "asset_class": asset_class.value,
                "blob": _spool._descriptor_dict(descriptor),
                "record_count": count,
            }
        )
        del records
        if progress_callback is not None:
            progress_callback(asset_class.value, index + 1, total_lanes)

    completed = datetime.now(timezone.utc)
    completed_active = _active_lanes(completed)
    if completed_active != active:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "scheduled comprehensive-discovery lane set changed during structural preparation"
        )
    material: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "release": _spool._release(values),
        "reference_manifest_id": reference_id,
        "prepared_as_of": timestamp.isoformat(),
        "completed_at": completed.isoformat(),
        "scheduled_lanes": [item.value for item in active],
        "reference_lanes": [item.value for item in reference_lanes],
        "record_count": total_records,
        "lanes": lanes,
        **_authority_fields(),
    }
    body = dict(material)
    body["manifest_id"] = _spool._digest(material)
    _spool._atomic_json(path, body)
    return load_structural_manifest(
        path,
        values=values,
        reference_manifest_id=reference_id,
        exact_as_of=completed,
    )


def bind_structural_manifest_for_fresh_epoch(
    values: dict[str, str],
    *,
    reference_manifest_id: str,
    exact_as_of: datetime,
) -> StructuralPreparationManifest:
    """Bind the exact compatible structural manifest; never build or repair it here."""

    active = _active_lanes(_aware(exact_as_of, field_name="exact_as_of"))
    path = _manifest_path(
        values,
        reference_manifest_id=reference_manifest_id,
        scheduled_lanes=active,
    )
    if not path.exists():
        raise _spool.ComprehensiveDiscoverySpoolError(
            "fresh comprehensive discovery has no compatible structural preparation manifest"
        )
    manifest = load_structural_manifest(
        path,
        values=values,
        reference_manifest_id=reference_manifest_id,
        exact_as_of=exact_as_of,
        verify_blobs=False,
    )
    values[_MANIFEST_ENV] = str(path)
    os.environ[_MANIFEST_ENV] = str(path)
    return manifest


def load_bound_reference_lane_records(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    exact_as_of: datetime,
) -> tuple[object, ...]:
    """Load one verified structural shard for an exact-epoch reference lane."""

    path_raw = str(values.get(_MANIFEST_ENV) or os.environ.get(_MANIFEST_ENV) or "").strip()
    if not path_raw:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "fresh comprehensive discovery structural manifest is not bound"
        )
    reference_id = str(
        values.get(_REFERENCE_MANIFEST_ID_ENV)
        or os.environ.get(_REFERENCE_MANIFEST_ID_ENV)
        or ""
    ).strip()
    if not reference_id:
        raise _spool.ComprehensiveDiscoverySpoolError(
            "fresh comprehensive discovery reference manifest is not bound"
        )
    manifest = load_structural_manifest(
        path_raw,
        values=values,
        reference_manifest_id=reference_id,
        exact_as_of=exact_as_of,
        verify_blobs=False,
    )
    if asset_class.value not in manifest.reference_lanes:
        raise _spool.ComprehensiveDiscoverySpoolError(
            f"structural preparation has no required reference lane: {asset_class.value}"
        )
    body = _spool._load_json(manifest.path, schema=_SCHEMA_VERSION)
    for item in body.get("lanes", ()):
        if not isinstance(item, Mapping) or str(item.get("asset_class") or "") != asset_class.value:
            continue
        records = _spool._load_pickle_blob(
            manifest.path.parent,
            _spool._descriptor(item.get("blob")),
        )
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise _spool.ComprehensiveDiscoverySpoolError(
                f"structural preparation lane is malformed: {asset_class.value}"
            )
        normalized = tuple(records)
        if len(normalized) != int(item.get("record_count", -1)):
            raise _spool.ComprehensiveDiscoverySpoolError(
                f"structural preparation lane count changed: {asset_class.value}"
            )
        if any(getattr(record, "asset_class", None) is not asset_class for record in normalized):
            raise _spool.ComprehensiveDiscoverySpoolError(
                f"structural preparation lane membership changed: {asset_class.value}"
            )
        return normalized
    raise _spool.ComprehensiveDiscoverySpoolError(
        f"structural preparation lane descriptor is missing: {asset_class.value}"
    )


__all__ = [
    "StructuralPreparationManifest",
    "_MANIFEST_ENV",
    "bind_structural_manifest_for_fresh_epoch",
    "load_bound_reference_lane_records",
    "load_structural_manifest",
    "prepare_structural_reference_catalogs",
]
