"""Release-bound structural catalog cache for comprehensive discovery retries.

This cache contains only merged catalog structure. It deliberately excludes provider
preselection, terminal screening, market features, certification nodes, and any evidence
that could authorize a candidate or portfolio action. A new evidence epoch must rebuild
all of those exact-time artifacts.

Reuse is permitted only inside the exact software release, policy version, and bound
reference-manifest identity that produced the structural catalog. The option lane is not
cacheable because its catalog is constructed directly from the requested timestamp.
Missing, corrupt, mismatched, future-dated, or authority-bearing cache entries are ignored
and callers rebuild the structural catalog fail-closed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import comprehensive_discovery_input_spool as _spool


_SCHEMA = "comprehensive-discovery-structural-cache.v1"
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _enabled(values: Mapping[str, str], asset_class: CandidateAssetClass) -> bool:
    return (
        asset_class is not CandidateAssetClass.OPTION
        and bool(str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip())
        and bool(str(values.get(_REFERENCE_MANIFEST_ID_ENV) or "").strip())
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
        "reference_manifest_id": str(values.get(_REFERENCE_MANIFEST_ID_ENV) or "").strip(),
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
) -> tuple[object, ...] | None:
    """Load a compatible structural catalog without changing its evidence timestamp."""

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
    if body.get("market_evidence_included") is not False:
        return None
    try:
        source_as_of = _spool._parse_timestamp(
            body.get("source_as_of"), field_name="structural_cache_source_as_of"
        )
    except (TypeError, ValueError, _spool.ComprehensiveDiscoverySpoolError):
        return None
    if source_as_of > requested:
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
    return tuple(loaded)


def publish_structural_catalog(
    values: Mapping[str, str],
    *,
    asset_class: CandidateAssetClass,
    policy_version: str,
    source_as_of: datetime,
    records: Sequence[object],
) -> bool:
    """Persist only structural merged-catalog records for a later fresh-epoch retry."""

    if not _enabled(values, asset_class):
        return False
    timestamp = _aware(source_as_of, field_name="structural_cache_source_as_of")
    metadata_path, blob_path = _paths(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
    )
    identity = _identity(values, asset_class=asset_class, policy_version=policy_version)

    # Never overwrite a valid compatible structural entry. The exact reference-manifest
    # identity makes the catalog immutable for this release/policy key, and preserving the
    # earliest source cutoff prevents a retry from pretending the structure was observed
    # later than it really was.
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
        "record_count": len(records),
        "blob": _spool._descriptor_dict(descriptor),
        "structural_only": True,
        "evidence_certified": False,
        "provider_preselection_included": False,
        "market_evidence_included": False,
        **_spool._authority_fields(),
    }
    _spool._atomic_json(metadata_path, body)
    return True


__all__ = [
    "load_structural_catalog",
    "publish_structural_catalog",
]
