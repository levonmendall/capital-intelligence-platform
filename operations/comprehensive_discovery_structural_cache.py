"""Release-bound structural catalog cache for comprehensive discovery retries.

This cache contains only merged catalog structure. It deliberately excludes provider
preselection, terminal screening, market features, certification nodes, and any evidence
that could authorize a candidate or portfolio action. A new evidence epoch must rebuild
all of those exact-time artifacts.

Reuse is permitted only inside the exact software release, policy version, and stable
fingerprint of the certified structural reference content. Reference-manifest ids, paths,
and capture/binding timestamps are audit lineage, not structural cache identity. The option
lane is not cacheable because its catalog is constructed directly from the requested
timestamp. Missing, corrupt, mismatched, future-dated, or authority-bearing cache entries
are ignored and callers rebuild the structural catalog fail-closed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import comprehensive_discovery_input_spool as _spool
from operations import reference_readiness as _reference


_SCHEMA = "comprehensive-discovery-structural-cache.v2"
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_REFERENCE_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_REFERENCE_STRUCTURAL_FINGERPRINT_ENV = (
    "CAPITAL_INTELLIGENCE_REFERENCE_STRUCTURAL_FINGERPRINT"
)


@dataclass(frozen=True, slots=True)
class StructuralCatalogCacheEntry:
    records: tuple[object, ...]
    raw_record_count: int
    source_as_of: datetime


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def reference_structural_fingerprint(values: Mapping[str, str]) -> str:
    """Fingerprint only integrity-verified, epoch-stable certified reference content."""

    configured_path = str(values.get(_REFERENCE_MANIFEST_PATH_ENV) or "").strip()
    configured_id = str(values.get(_REFERENCE_MANIFEST_ID_ENV) or "").strip()
    if not configured_path or not configured_id:
        raise _reference.ReferenceReadinessError(
            "qualified reference manifest path/id are required for structural fingerprint"
        )
    path = Path(configured_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _reference.ReferenceReadinessError(
            "bound reference manifest is unavailable for structural fingerprint"
        ) from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _reference._SCHEMA_VERSION:
        raise _reference.ReferenceReadinessError(
            "bound reference manifest schema is invalid for structural fingerprint"
        )
    expected_id = str(payload.get("manifest_id") or "").strip()
    material = {key: value for key, value in payload.items() if key != "manifest_id"}
    if not expected_id or _reference._fingerprint(material) != expected_id:
        raise _reference.ReferenceReadinessError(
            "bound reference manifest integrity check failed for structural fingerprint"
        )
    if expected_id != configured_id:
        raise _reference.ReferenceReadinessError(
            "bound reference manifest identity changed before structural fingerprint"
        )
    if str(payload.get("release") or "").strip() != _spool._release(values):
        raise _reference.ReferenceReadinessError(
            "bound reference manifest release changed before structural fingerprint"
        )
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        raise _reference.ReferenceReadinessError(
            "bound reference manifest authority is invalid for structural fingerprint"
        )
    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, Mapping):
        raise _reference.ReferenceReadinessError(
            "bound reference manifest catalogs are missing for structural fingerprint"
        )
    for records in catalogs.values():
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise _reference.ReferenceReadinessError(
                "bound reference manifest catalog lane is malformed"
            )
        if any(not isinstance(record, Mapping) for record in records):
            raise _reference.ReferenceReadinessError(
                "bound reference manifest catalog record is malformed"
            )

    # Deliberately exclude captured_at, bound_at, component ids, manifest id/path, and
    # release. The cache separately binds release and policy. The material below is the
    # certified structural content that determines catalog reconstruction and lane scope.
    structural_material = {
        "config_fingerprint": str(payload.get("config_fingerprint") or ""),
        "eodhd_exchanges": list(payload.get("eodhd_exchanges") or ()),
        "futures_roots": list(payload.get("futures_roots") or ()),
        "active_lanes": list(payload.get("active_lanes") or ()),
        "catalogs": {str(name): list(records) for name, records in catalogs.items()},
    }
    return _reference._fingerprint(structural_material)


def bind_reference_structural_fingerprint(values: dict[str, str]) -> str:
    """Bind one verified structural fingerprint for all finite children in this attempt."""

    fingerprint = reference_structural_fingerprint(values)
    values[_REFERENCE_STRUCTURAL_FINGERPRINT_ENV] = fingerprint
    return fingerprint


def _structural_fingerprint(values: Mapping[str, str]) -> str:
    return str(values.get(_REFERENCE_STRUCTURAL_FINGERPRINT_ENV) or "").strip()


def _enabled(values: Mapping[str, str], asset_class: CandidateAssetClass) -> bool:
    return (
        asset_class is not CandidateAssetClass.OPTION
        and bool(str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip())
        and bool(_structural_fingerprint(values))
        and _spool._release(values) not in {"", "unknown"}
    )


def _identity(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    policy_version: str,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA,
        "release": _spool._release(values),
        "reference_structural_fingerprint": _structural_fingerprint(values),
        "policy_version": str(policy_version),
        "asset_class": asset_class.value,
    }


def _directory(values: Mapping[str, str]) -> Path:
    root = Path(str(values["CAPITAL_INTELLIGENCE_DATA_DIR"]).strip()).expanduser()
    return root / "comprehensive-discovery-structural-cache" / _spool._safe_release(
        _spool._release(values)
    )


def _paths(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    policy_version: str,
) -> tuple[Path, Path]:
    identity = _identity(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
    )
    key = _spool._digest(identity)
    directory = _directory(values)
    return directory / f"{key}.json", directory / f"{key}.pkl"


def load_structural_catalog(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    policy_version: str,
    requested_as_of: datetime,
) -> StructuralCatalogCacheEntry | None:
    """Load compatible structure without changing or certifying its observation time."""

    if not _enabled(values, asset_class):
        return None
    requested = _aware(requested_as_of, field_name="structural_cache_requested_as_of")
    metadata_path, blob_path = _paths(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
    )
    try:
        body = _spool._load_json(metadata_path, schema=_SCHEMA)
    except (OSError, TypeError, ValueError, _spool.ComprehensiveDiscoverySpoolError):
        return None
    identity = _identity(values, asset_class=asset_class, policy_version=policy_version)
    if any(body.get(key) != value for key, value in identity.items()):
        return None
    if body.get("structural_only") is not True or body.get("evidence_certified") is not False:
        return None
    if body.get("provider_preselection_included") is not False:
        return None
    if body.get("terminal_screening_included") is not False:
        return None
    if body.get("market_evidence_included") is not False:
        return None
    try:
        source_as_of = _spool._parse_timestamp(
            body.get("source_as_of"), field_name="structural_cache_source_as_of"
        )
        raw_record_count = int(body.get("raw_record_count", -1))
    except (TypeError, ValueError, _spool.ComprehensiveDiscoverySpoolError):
        return None
    if source_as_of > requested or raw_record_count < 0:
        return None
    try:
        descriptor = _spool._descriptor(body.get("blob"))
        if descriptor.relative_path != blob_path.name:
            return None
        _spool._verify_blob(metadata_path.parent, descriptor)
        loaded = _spool._load_pickle_blob(metadata_path.parent, descriptor)
    except (OSError, TypeError, ValueError, _spool.ComprehensiveDiscoverySpoolError):
        return None
    if not isinstance(loaded, Sequence) or isinstance(loaded, (str, bytes, bytearray)):
        return None
    if int(body.get("record_count", -1)) != len(loaded):
        return None
    return StructuralCatalogCacheEntry(
        records=tuple(loaded),
        raw_record_count=raw_record_count,
        source_as_of=source_as_of,
    )


def publish_structural_catalog(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    policy_version: str,
    source_as_of: datetime,
    raw_record_count: int,
    records: Sequence[object],
) -> bool:
    """Persist merged catalog structure only; never exact-epoch market qualification."""

    if not _enabled(values, asset_class):
        return False
    if raw_record_count < 0:
        raise ValueError("raw_record_count must be nonnegative")
    timestamp = _aware(source_as_of, field_name="structural_cache_source_as_of")
    metadata_path, blob_path = _paths(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
    )
    identity = _identity(values, asset_class=asset_class, policy_version=policy_version)

    # Do not overwrite a valid compatible entry. The exact release/policy/content key
    # makes the structural input immutable, and preserving its earliest source cutoff
    # prevents a retry from pretending that structural information was observed later.
    existing = load_structural_catalog(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if existing is not None:
        return True

    descriptor = _spool._write_pickle_blob(
        metadata_path.parent,
        blob_path.name,
        tuple(records),
    )
    body: dict[str, object] = {
        **identity,
        "source_as_of": timestamp.isoformat(),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "reference_manifest_id_at_publication": str(
            values.get(_REFERENCE_MANIFEST_ID_ENV) or ""
        ).strip(),
        "raw_record_count": int(raw_record_count),
        "record_count": len(records),
        "blob": _spool._descriptor_dict(descriptor),
        "structural_only": True,
        "evidence_certified": False,
        "provider_preselection_included": False,
        "terminal_screening_included": False,
        "market_evidence_included": False,
        **_spool._authority_fields(),
    }
    _spool._atomic_json(metadata_path, body)
    return True


__all__ = [
    "StructuralCatalogCacheEntry",
    "bind_reference_structural_fingerprint",
    "load_structural_catalog",
    "publish_structural_catalog",
    "reference_structural_fingerprint",
]
