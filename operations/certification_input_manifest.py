"""Immutable handoff from the continuous evidence owner to CIO consumers.

This module establishes the all-market certification v2 boundary without changing any
investment strategy, screening threshold, specialist authority, construction rule, or
paper-execution control.

The continuous evidence plane owns provider acquisition. A CIO/certification consumer
may only freeze a point-in-time snapshot that already exists and is fresh enough. The
resulting immutable record binds identities that must not be conflated:

* application release identity (R),
* evidence generation / point-in-time snapshot identity (G),
* immutable global discovery snapshot identity, and
* evidence-policy compatibility identity (P).

Publishing this record performs no provider, discovery, reference, public-information,
or history refresh. Missing or stale evidence fails closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from operations import continuous_evidence_plane as _plane
from operations.certification_state_machine import (
    CertificationState,
    advance_certification_state,
)
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    QualifiedComprehensiveDiscoverySnapshot,
    load_qualified_comprehensive_discovery_snapshot,
)


_SCHEMA = "all-market-certification-input.v2"
_POLICY_SCHEMA = "all-market-evidence-policy-compatibility.v1"
_COMPATIBILITY_ENV_NAMES = (
    "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED",
    "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS",
    "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY",
    "CAPITAL_INTELLIGENCE_COMPOSITIONAL_CERTIFICATION_ENABLED",
    "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE",
)


class CertificationInputError(RuntimeError):
    """Raised when an immutable provider-free CIO input cannot be established."""


@dataclass(frozen=True, slots=True)
class CertificationInputRecord:
    record_id: str
    release: str
    evidence_generation_id: str
    evidence_as_of: datetime
    snapshot_id: str
    global_discovery_snapshot_id: str
    cutoff: datetime
    reference_manifest_id: str
    policy_compatibility_hash: str
    path: Path


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _safe(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise CertificationInputError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for certification input"
        )
    return Path(raw).expanduser() / "all-market-certification-v2"


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as error:
            raise CertificationInputError(
                "immutable certification input cannot be read"
            ) from error
        if existing != encoded:
            raise CertificationInputError(
                f"immutable certification input collision at {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise CertificationInputError(
                f"immutable certification input collision at {path.name}"
            )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["integrity_sha256"] = _digest(payload)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(body, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _policy_material(
    values: Mapping[str, str],
    *,
    generation: _plane.EvidencePlaneGeneration,
) -> Mapping[str, object]:
    return {
        "schema_version": _POLICY_SCHEMA,
        "reference_manifest_id": generation.reference_manifest_id,
        "scheduled_lanes": list(generation.scheduled_lanes),
        "environment": {
            name: values.get(name, "").strip()
            for name in _COMPATIBILITY_ENV_NAMES
        },
        "paper_only": True,
        "real_money_authorized": False,
    }


def freeze_certification_input(
    *,
    cutoff: datetime,
    values: Mapping[str, str] | None = None,
    snapshot: _plane.PointInTimeEvidenceSnapshot | None = None,
    global_snapshot: QualifiedComprehensiveDiscoverySnapshot | None = None,
) -> CertificationInputRecord:
    """Freeze an immutable provider-free R+G+global-snapshot+P CIO handoff.

    The function deliberately calls ``ensure_point_in_time_snapshot`` with
    ``allow_refresh=False`` when a PIT snapshot was not supplied. The global discovery
    component is loaded by exact evidence-generation cutoff with no provider fallback.
    """

    resolved = dict(os.environ if values is None else values)
    requested = _aware(cutoff, field_name="certification_cutoff")
    frozen = snapshot or _plane.ensure_point_in_time_snapshot(
        cutoff=requested,
        values=resolved,
        allow_refresh=False,
    )
    if _aware(frozen.cutoff, field_name="snapshot_cutoff") != requested:
        raise CertificationInputError(
            "point-in-time snapshot cutoff does not match certification cutoff"
        )

    generation = _plane.load_latest_evidence_plane(resolved)
    if generation is None:
        raise CertificationInputError("qualified evidence generation is unavailable")
    if generation.generation_id != frozen.plane_generation_id:
        raise CertificationInputError(
            "point-in-time snapshot is not bound to the latest qualified generation"
        )
    if generation.reference_manifest_id != frozen.reference_manifest_id:
        raise CertificationInputError(
            "point-in-time snapshot reference manifest does not match evidence generation"
        )

    try:
        qualified_global = global_snapshot or load_qualified_comprehensive_discovery_snapshot(
            evidence_as_of=generation.as_of,
            values=resolved,
        )
    except ComprehensiveDiscoverySnapshotError as error:
        raise CertificationInputError(
            f"qualified global discovery snapshot is unavailable: {error}"
        ) from error
    if _aware(
        qualified_global.evidence_as_of,
        field_name="global_discovery_evidence_as_of",
    ) != generation.as_of:
        raise CertificationInputError(
            "global discovery snapshot is not bound to the qualified evidence generation"
        )

    release = _release(resolved)
    policy_material = _policy_material(resolved, generation=generation)
    policy_hash = _digest(policy_material)
    material: dict[str, object] = {
        "schema_version": _SCHEMA,
        "release": release,
        "evidence_generation_id": generation.generation_id,
        "evidence_as_of": generation.as_of.isoformat(),
        "snapshot_id": frozen.snapshot_id,
        "snapshot_cutoff": requested.isoformat(),
        "global_discovery_snapshot_id": qualified_global.snapshot_id,
        "global_discovery_state_scope": {
            "held_symbols": list(qualified_global.held_symbols),
            "tracked_symbols": list(qualified_global.tracked_symbols),
        },
        "reference_manifest_id": generation.reference_manifest_id,
        "historical_scope_count": generation.historical_scope_count,
        "historical_coverage_digest": generation.historical_coverage_digest,
        "scheduled_lanes": list(generation.scheduled_lanes),
        "policy_compatibility_hash": policy_hash,
        "policy_material": policy_material,
        "evidence_owner": "continuous_evidence_plane",
        "consumer_provider_refresh_permitted": False,
        "evidence_certification": "certified",
        "snapshot_certification": "frozen",
        "cio_eligible": True,
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    record_id = _digest(material)
    payload = {**material, "record_id": record_id}
    path = (
        _root(resolved)
        / "inputs"
        / _safe(release)
        / f"{record_id}.json"
    )
    _immutable_json(path, payload)

    # The evidence owner and snapshot freezer are separate durable facts. Later owners
    # can advance this same certification_id through screening, committee, CIO,
    # construction, implementation/no-action, and final certification without replaying
    # acquisition or inferring missing stages.
    advance_certification_state(
        certification_id=record_id,
        target=CertificationState.EVIDENCE_READY,
        source_id=generation.generation_id,
        values=resolved,
        detail="qualified evidence generation accepted by provider-free consumer",
        metadata={
            "reference_manifest_id": generation.reference_manifest_id,
            "evidence_as_of": generation.as_of.isoformat(),
            "global_discovery_snapshot_id": qualified_global.snapshot_id,
        },
    )
    advance_certification_state(
        certification_id=record_id,
        target=CertificationState.SNAPSHOT_FROZEN,
        source_id=frozen.snapshot_id,
        values=resolved,
        detail="point-in-time CIO input snapshot frozen",
        metadata={
            "snapshot_cutoff": requested.isoformat(),
            "policy_compatibility_hash": policy_hash,
            "global_discovery_snapshot_id": qualified_global.snapshot_id,
        },
    )

    _atomic_json(
        _root(resolved) / "ledger" / _safe(release) / "latest-input.json",
        {
            "schema_version": _SCHEMA,
            "record_id": record_id,
            "release": release,
            "evidence_generation_id": generation.generation_id,
            "snapshot_id": frozen.snapshot_id,
            "global_discovery_snapshot_id": qualified_global.snapshot_id,
            "snapshot_cutoff": requested.isoformat(),
            "policy_compatibility_hash": policy_hash,
            "record_path": str(path),
            "certification_state": CertificationState.SNAPSHOT_FROZEN.value,
            "cio_eligible": True,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )
    return CertificationInputRecord(
        record_id=record_id,
        release=release,
        evidence_generation_id=generation.generation_id,
        evidence_as_of=generation.as_of,
        snapshot_id=frozen.snapshot_id,
        global_discovery_snapshot_id=qualified_global.snapshot_id,
        cutoff=requested,
        reference_manifest_id=generation.reference_manifest_id,
        policy_compatibility_hash=policy_hash,
        path=path,
    )


__all__ = [
    "CertificationInputError",
    "CertificationInputRecord",
    "freeze_certification_input",
]
