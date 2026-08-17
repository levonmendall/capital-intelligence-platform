"""Maintain exact-release evidence outside the governed CIO diagnostic.

This module is the operational owner for expensive reference/public/discovery work. It
reuses freshness-qualified component checkpoints, publishes an integrity-bound evidence
plane generation, archives every published generation immutably, and exposes a disk-only
loader that lets the bounded CIO watchdog consume the already-qualified reference
manifest without calling external providers.

Nothing in this module has investment, specialist, construction, execution, or real-money
authority. Missing, stale, release-mismatched, configuration-mismatched, incomplete, or
corrupted evidence remains fail-closed.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, MutableMapping

from operations import continuous_evidence_plane as _plane
from operations.reference_readiness import (
    ReferenceReadinessError,
    ReferenceReadinessManifest,
    load_reference_catalogs,
)

_REFERENCE_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_DEFAULT_MAX_AGE_SECONDS = 900.0
_MAX_PREPARATION_PASSES = 2


@dataclass(frozen=True, slots=True)
class EvidenceMaintenanceResult:
    generation: _plane.EvidencePlaneGeneration
    state: str
    refreshed: bool
    preparation_passes: int
    archived_generation_path: Path


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


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _max_age_seconds(values: Mapping[str, str]) -> float:
    raw = values.get("CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_MAX_AGE_SECONDS
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS must be numeric"
        ) from error
    if value <= 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS must be positive"
        )
    return value


def _plane_root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise _plane.ContinuousEvidencePlaneError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for evidence maintenance"
        )
    return Path(raw).expanduser() / "continuous_evidence_plane"


def _latest_release(values: Mapping[str, str]) -> str | None:
    path = _plane_root(values) / "latest-qualified.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return str(payload.get("release") or "").strip() or None


def _generation_qualified(
    generation: _plane.EvidencePlaneGeneration | None,
    *,
    values: Mapping[str, str],
    cutoff: datetime,
    reference_manifest_id: str,
) -> bool:
    if generation is None:
        return False
    timestamp = _aware(cutoff, field_name="evidence_maintenance_cutoff")
    age = timestamp - generation.as_of
    return (
        _latest_release(values) == _release(values)
        and timedelta(0) <= age <= timedelta(seconds=_max_age_seconds(values))
        and generation.completed_at >= generation.as_of
        and generation.reference_manifest_id == reference_manifest_id
        and bool(generation.historical_coverage_digest)
        and generation.public_live_state not in {"failed", "disabled"}
    )


def _default_public_collector(timestamp: datetime):
    """Qualify required public information through durable requirement-group checkpoints."""

    from operations.public_live_requirement_qualification import (
        maintain_required_public_live_requirements,
    )

    return maintain_required_public_live_requirements(
        as_of=timestamp,
        values=os.environ,
    )


@contextmanager
def _bound_reference_manifest(reference: object) -> Iterator[None]:
    manifest_id = str(getattr(reference, "manifest_id", "")).strip()
    manifest_path = getattr(reference, "path", None)
    if not manifest_id:
        raise _plane.ContinuousEvidencePlaneError(
            "reference maintenance did not publish a manifest identifier"
        )
    if manifest_path is None:
        # Test/injected discovery paths may not require the process-global binding. The
        # production ReferenceReadinessManifest always supplies an exact path.
        yield
        return

    path = str(Path(manifest_path).expanduser())
    prior_path = os.environ.get(_REFERENCE_MANIFEST_PATH_ENV)
    prior_id = os.environ.get(_REFERENCE_MANIFEST_ID_ENV)
    os.environ[_REFERENCE_MANIFEST_PATH_ENV] = path
    os.environ[_REFERENCE_MANIFEST_ID_ENV] = manifest_id
    try:
        yield
    finally:
        if prior_path is None:
            os.environ.pop(_REFERENCE_MANIFEST_PATH_ENV, None)
        else:
            os.environ[_REFERENCE_MANIFEST_PATH_ENV] = prior_path
        if prior_id is None:
            os.environ.pop(_REFERENCE_MANIFEST_ID_ENV, None)
        else:
            os.environ[_REFERENCE_MANIFEST_ID_ENV] = prior_id


def _archive_generation(
    values: Mapping[str, str],
    generation: _plane.EvidencePlaneGeneration,
) -> Path:
    """Persist the published generation at an immutable content-addressed path."""

    source = _plane_root(values) / "latest-qualified.json"
    # load_latest_evidence_plane performs schema, authority and integrity validation
    # before bytes are copied into immutable lineage.
    validated = _plane.load_latest_evidence_plane(values)
    if validated is None or validated.generation_id != generation.generation_id:
        raise _plane.ContinuousEvidencePlaneError(
            "published evidence generation changed before immutable archival"
        )
    try:
        material = source.read_bytes()
    except OSError as error:
        raise _plane.ContinuousEvidencePlaneError(
            "published evidence generation cannot be archived"
        ) from error

    target = (
        _plane_root(values)
        / "generations"
        / _safe(_release(values))
        / f"{generation.generation_id}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as error:
            raise _plane.ContinuousEvidencePlaneError(
                "immutable evidence generation cannot be verified"
            ) from error
        if existing != material:
            raise _plane.ContinuousEvidencePlaneError(
                "immutable evidence generation content mismatch"
            )
        return target

    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(material)
        os.replace(temporary, target)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise _plane.ContinuousEvidencePlaneError(
            "immutable evidence generation cannot be published"
        ) from error
    return target


def maintain_continuous_evidence_plane(
    *,
    as_of: datetime | None = None,
    values: Mapping[str, str] | None = None,
    reference_preparer: Callable[[Mapping[str, str]], object] | None = None,
    public_collector: Callable[[datetime], object] | None = None,
    discovery: Callable[[datetime], object] | None = None,
) -> EvidenceMaintenanceResult:
    """Refresh only when the exact-release qualified generation is missing or stale.

    Reference readiness always runs first because it is component-checkpointed and is the
    authoritative configuration/freshness watermark. If the current evidence generation
    is recent and bound to that exact manifest, expensive public/discovery work is skipped.
    A cold pass that exceeds the evidence-plane SLA receives one warm delta pass; failure
    to publish a current generation after that remains fail-closed.
    """

    resolved = dict(os.environ if values is None else values)
    if not _plane.evidence_plane_enabled(resolved):
        raise _plane.ContinuousEvidencePlaneError("continuous evidence plane is disabled")
    requested = _aware(
        datetime.now(timezone.utc) if as_of is None else as_of,
        field_name="evidence_maintenance_as_of",
    )
    if requested > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise _plane.ContinuousEvidencePlaneError(
            "continuous evidence maintenance cannot prepare a future cutoff"
        )

    prepare_reference = reference_preparer or _plane._default_reference_preparer
    collect_public = public_collector or _default_public_collector
    run_discovery = discovery or _plane._default_discovery

    reference = prepare_reference(resolved)
    manifest_id = str(getattr(reference, "manifest_id", "")).strip()
    if not manifest_id:
        raise _plane.ContinuousEvidencePlaneError(
            "reference maintenance did not publish a manifest identifier"
        )

    current = _plane.load_latest_evidence_plane(resolved)
    if _generation_qualified(
        current,
        values=resolved,
        cutoff=requested,
        reference_manifest_id=manifest_id,
    ):
        archive = _archive_generation(resolved, current)
        return EvidenceMaintenanceResult(
            generation=current,
            state="current",
            refreshed=False,
            preparation_passes=0,
            archived_generation_path=archive,
        )

    generation: _plane.EvidencePlaneGeneration | None = None
    for preparation_pass in range(1, _MAX_PREPARATION_PASSES + 1):
        pass_cutoff = requested if preparation_pass == 1 else datetime.now(timezone.utc)
        if preparation_pass > 1:
            reference = prepare_reference(resolved)
            manifest_id = str(getattr(reference, "manifest_id", "")).strip()
            if not manifest_id:
                raise _plane.ContinuousEvidencePlaneError(
                    "reference maintenance lost its manifest identifier"
                )

        with _bound_reference_manifest(reference):
            generation = _plane.refresh_continuous_evidence_plane(
                as_of=pass_cutoff,
                values=resolved,
                reference_preparer=lambda _resolved, prepared=reference: prepared,
                public_collector=collect_public,
                discovery=run_discovery,
            )
        archive = _archive_generation(resolved, generation)
        final_cutoff = datetime.now(timezone.utc)
        if _generation_qualified(
            generation,
            values=resolved,
            cutoff=final_cutoff,
            reference_manifest_id=manifest_id,
        ):
            return EvidenceMaintenanceResult(
                generation=generation,
                state="refreshed",
                refreshed=True,
                preparation_passes=preparation_pass,
                archived_generation_path=archive,
            )

    raise _plane.ContinuousEvidencePlaneError(
        "continuous evidence maintenance could not publish a current exact-release "
        "generation after two bounded preparation passes"
    )


def _current_reference_path(values: Mapping[str, str]) -> Path:
    configured = values.get(_REFERENCE_MANIFEST_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    data_root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_root / "reference_readiness" / f"instrument-master-{_safe(_release(values))}.json"


def load_prequalified_reference_manifest(
    values: MutableMapping[str, str],
) -> ReferenceReadinessManifest:
    """Load the exact evidence-plane reference manifest without provider acquisition."""

    snapshot = _plane.ensure_point_in_time_snapshot(
        values=values,
        allow_refresh=False,
    )
    path = _current_reference_path(values)
    values[_REFERENCE_MANIFEST_PATH_ENV] = str(path)
    values[_REFERENCE_MANIFEST_ID_ENV] = snapshot.reference_manifest_id

    from operations import _comprehensive_market_discovery_v4 as discovery

    config = discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(config)
    catalogs = load_reference_catalogs(
        as_of=snapshot.cutoff,
        config=config,
        values=values,
    )
    if catalogs is None:
        raise ReferenceReadinessError(
            "prequalified reference manifest was not bound for the CIO cutoff"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise ReferenceReadinessError(
            "prequalified reference manifest is unreadable"
        ) from error
    if not isinstance(payload, Mapping):
        raise ReferenceReadinessError(
            "prequalified reference manifest is not an object"
        )
    manifest_id = str(payload.get("manifest_id") or "").strip()
    if manifest_id != snapshot.reference_manifest_id:
        raise ReferenceReadinessError(
            "point-in-time evidence generation is not bound to the current reference manifest"
        )
    if str(payload.get("release") or "").strip() != _release(values):
        raise ReferenceReadinessError(
            "prequalified reference manifest release does not match the diagnostic release"
        )

    try:
        captured_at = datetime.fromisoformat(
            str(payload.get("captured_at") or "").replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ReferenceReadinessError(
            "prequalified reference manifest captured_at is invalid"
        ) from error
    captured_at = _aware(captured_at, field_name="reference_manifest_captured_at")
    counts = tuple(
        sorted((asset_class.value, len(records)) for asset_class, records in catalogs.items())
    )
    return ReferenceReadinessManifest(
        manifest_id=manifest_id,
        release=_release(values),
        captured_at=captured_at,
        config_fingerprint=str(payload.get("config_fingerprint") or ""),
        eodhd_exchanges=tuple(str(item) for item in payload.get("eodhd_exchanges") or ()),
        futures_roots=tuple(str(item) for item in payload.get("futures_roots") or ()),
        catalog_counts=counts,
        path=path,
    )


__all__ = [
    "EvidenceMaintenanceResult",
    "load_prequalified_reference_manifest",
    "maintain_continuous_evidence_plane",
]
