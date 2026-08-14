"""Continuously prepare governed evidence and freeze point-in-time CIO snapshots.

The evidence plane is operational only.  It reuses the existing reference-readiness,
public-information, comprehensive-discovery, and persistent-history paths so expensive
provider work happens between CIO decisions instead of inside the bounded CIO analysis
window.  A qualified plane generation never authorizes an investment decision.

Before a CIO cycle starts, ``ensure_point_in_time_snapshot`` verifies that a complete
plane generation is recent enough for the requested cutoff.  When background
preparation is missing or stale, the same evidence-only preparation runs synchronously
*before* the CIO clock starts.  The resulting snapshot is an integrity-bound manifest
that references the existing persistent stores; it does not duplicate raw evidence.

Current quotes, spreads, liquidity, option IV/Greeks, macro/public releases and any other
evidence with a tighter decision-time freshness contract remain subject to their
existing production-context checks.  Missing evidence always fails closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping


_PLANE_SCHEMA = "continuous-evidence-plane.v1"
_SNAPSHOT_SCHEMA = "point-in-time-evidence-snapshot.v1"
_DEFAULT_MAX_AGE_SECONDS = 900.0


class ContinuousEvidencePlaneError(RuntimeError):
    """Raised when a complete point-in-time evidence plane cannot be established."""


@dataclass(frozen=True, slots=True)
class EvidencePlaneGeneration:
    generation_id: str
    as_of: datetime
    completed_at: datetime
    reference_manifest_id: str
    scheduled_lanes: tuple[str, ...]
    historical_scope_count: int
    historical_coverage_digest: str
    public_live_state: str


@dataclass(frozen=True, slots=True)
class PointInTimeEvidenceSnapshot:
    snapshot_id: str
    cutoff: datetime
    plane_generation_id: str
    plane_as_of: datetime
    reference_manifest_id: str
    historical_scope_count: int
    historical_coverage_digest: str
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


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def evidence_plane_enabled(values: Mapping[str, str] | None = None) -> bool:
    resolved = os.environ if values is None else values
    if not resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip():
        return False
    return _boolean(
        resolved,
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED",
        True,
    )


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
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS must be positive"
        )
    return value


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise ContinuousEvidencePlaneError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for the continuous evidence plane"
        )
    return Path(raw).expanduser() / "continuous_evidence_plane"


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


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    material = dict(payload)
    material["integrity_sha256"] = _digest(payload)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(material, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_integrity_json(path: Path, *, schema: str) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise ContinuousEvidencePlaneError(
            f"evidence-plane manifest is unreadable: {path.name}"
        ) from error
    if not isinstance(raw, Mapping):
        raise ContinuousEvidencePlaneError(
            f"evidence-plane manifest is not an object: {path.name}"
        )
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        raise ContinuousEvidencePlaneError(
            f"evidence-plane manifest integrity mismatch: {path.name}"
        )
    if payload.get("schema_version") != schema:
        raise ContinuousEvidencePlaneError(
            f"evidence-plane manifest schema mismatch: {path.name}"
        )
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        raise ContinuousEvidencePlaneError(
            f"evidence-plane authority boundary is invalid: {path.name}"
        )
    return payload


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ContinuousEvidencePlaneError(
            f"{field_name} is not a valid timestamp"
        ) from error
    return _aware(parsed, field_name=field_name)


def _historical_coverage_summary(
    values: Mapping[str, str],
    *,
    as_of: datetime,
) -> tuple[int, str]:
    """Return an integrity-checked digest of the reusable history coverage table."""

    data_root = Path(values["CAPITAL_INTELLIGENCE_DATA_DIR"]).expanduser()
    path = data_root / "historical_evidence" / "market_history.sqlite3"
    if not path.exists():
        return 0, _digest(())

    timestamp = _aware(as_of, field_name="historical_coverage_as_of")
    try:
        connection = sqlite3.connect(str(path), timeout=30.0)
    except sqlite3.Error as error:
        raise ContinuousEvidencePlaneError(
            "persistent historical evidence database is unavailable"
        ) from error
    try:
        schema = connection.execute(
            "SELECT value FROM historical_evidence_meta WHERE key='schema_version'"
        ).fetchone()
        if schema is None or str(schema[0]) != "persistent-historical-evidence.v1":
            raise ContinuousEvidencePlaneError(
                "persistent historical evidence schema is not qualified"
            )
        rows = connection.execute(
            """
            SELECT asset_class, instrument_identity, provider_scope,
                   maximum_history_days, requested_as_of, integrity_sha256
            FROM historical_evidence_coverage
            ORDER BY asset_class, instrument_identity, provider_scope
            """
        ).fetchall()
    except sqlite3.Error as error:
        raise ContinuousEvidencePlaneError(
            "persistent historical evidence coverage cannot be read"
        ) from error
    finally:
        connection.close()

    material: list[Mapping[str, object]] = []
    for asset_class, identity, provider_scope, maximum_days, requested_raw, integrity in rows:
        payload = {
            "asset_class": str(asset_class),
            "instrument_identity": str(identity),
            "provider_scope": str(provider_scope),
            "maximum_history_days": int(maximum_days),
            "requested_as_of": str(requested_raw),
        }
        if str(integrity) != _digest(payload):
            raise ContinuousEvidencePlaneError(
                "persistent historical evidence coverage integrity mismatch"
            )
        requested = _parse_timestamp(
            requested_raw,
            field_name="historical_requested_as_of",
        )
        if requested > timestamp:
            # A snapshot may never depend on a provider refresh that happened after
            # its point-in-time cutoff.
            continue
        material.append(payload)
    return len(material), _digest(material)


def _default_reference_preparer(values: Mapping[str, str]):
    from operations.cme_futures_reference_runtime import (
        install_cme_futures_reference_lineage,
    )
    from operations.generalized_reference_readiness import prepare_reference_readiness
    from providers.cme_futures_reference_executable import (
        CmeExecutableFuturesReferenceProvider,
    )
    from providers.massive_futures_reference_rate_resilient import (
        MassiveFuturesReferenceProvider,
    )

    install_cme_futures_reference_lineage()
    return prepare_reference_readiness(
        values,
        massive_futures_provider=CmeExecutableFuturesReferenceProvider(
            fallback_provider=MassiveFuturesReferenceProvider(),
            values=values,
        ),
    )


def _default_public_collector(as_of: datetime):
    from public_live_collection_runtime import collect_public_live_information_if_due

    return collect_public_live_information_if_due(now=as_of, force=True)


def _default_discovery(as_of: datetime):
    from operations.comprehensive_market_discovery import discover_comprehensive_markets

    return discover_comprehensive_markets(as_of=as_of)


def _scheduled_lanes(as_of: datetime) -> tuple[str, ...]:
    from operations.comprehensive_market_discovery_legacy import scheduled_discovery_lanes

    return tuple(sorted(item.value for item in scheduled_discovery_lanes(as_of)))


def refresh_continuous_evidence_plane(
    *,
    as_of: datetime | None = None,
    values: Mapping[str, str] | None = None,
    reference_preparer: Callable[[Mapping[str, str]], object] | None = None,
    public_collector: Callable[[datetime], object] | None = None,
    discovery: Callable[[datetime], object] | None = None,
) -> EvidencePlaneGeneration:
    """Prepare all reusable evidence without invoking specialists, CIO, or execution."""

    resolved = dict(os.environ if values is None else values)
    if not evidence_plane_enabled(resolved):
        raise ContinuousEvidencePlaneError("continuous evidence plane is disabled")
    timestamp = _aware(
        datetime.now(timezone.utc) if as_of is None else as_of,
        field_name="evidence_plane_as_of",
    )
    now = datetime.now(timezone.utc)
    if timestamp > now + timedelta(seconds=5):
        raise ContinuousEvidencePlaneError(
            "continuous evidence plane cannot prepare a future cutoff"
        )

    prepare_reference = reference_preparer or _default_reference_preparer
    collect_public = public_collector or _default_public_collector
    run_discovery = discovery or _default_discovery

    try:
        reference = prepare_reference(resolved)
        public_result = collect_public(timestamp)
        public_state = str(getattr(public_result, "state", "available"))
        if public_state == "failed":
            raise ContinuousEvidencePlaneError(
                "public live information refresh failed"
            )
        # A successful governed comprehensive discovery is the completeness barrier:
        # it hydrates reference/history stores but does not invoke specialists or CIO.
        run_discovery(timestamp)
        scope_count, coverage_digest = _historical_coverage_summary(
            resolved,
            as_of=timestamp,
        )
    except ContinuousEvidencePlaneError:
        raise
    except Exception as error:
        raise ContinuousEvidencePlaneError(
            f"continuous evidence preparation failed: {type(error).__name__}: {error}"
        ) from error

    reference_id = str(getattr(reference, "manifest_id", "")).strip()
    if not reference_id:
        raise ContinuousEvidencePlaneError(
            "reference readiness did not publish a manifest identifier"
        )
    completed = datetime.now(timezone.utc)
    lanes = _scheduled_lanes(timestamp)
    generation_material = {
        "schema_version": _PLANE_SCHEMA,
        "release": _release(resolved),
        "as_of": timestamp.isoformat(),
        "completed_at": completed.isoformat(),
        "reference_manifest_id": reference_id,
        "scheduled_lanes": list(lanes),
        "historical_scope_count": scope_count,
        "historical_coverage_digest": coverage_digest,
        "public_live_state": public_state,
        "comprehensive_discovery_complete": True,
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    generation_id = _digest(generation_material)
    payload = dict(generation_material)
    payload["generation_id"] = generation_id
    _atomic_json(_root(resolved) / "latest-qualified.json", payload)
    return EvidencePlaneGeneration(
        generation_id=generation_id,
        as_of=timestamp,
        completed_at=completed,
        reference_manifest_id=reference_id,
        scheduled_lanes=lanes,
        historical_scope_count=scope_count,
        historical_coverage_digest=coverage_digest,
        public_live_state=public_state,
    )


def load_latest_evidence_plane(
    values: Mapping[str, str] | None = None,
) -> EvidencePlaneGeneration | None:
    resolved = dict(os.environ if values is None else values)
    if not evidence_plane_enabled(resolved):
        return None
    payload = _read_integrity_json(
        _root(resolved) / "latest-qualified.json",
        schema=_PLANE_SCHEMA,
    )
    if payload is None:
        return None
    generation_id = str(payload.get("generation_id") or "")
    material = dict(payload)
    material.pop("generation_id", None)
    if not generation_id or generation_id != _digest(material):
        raise ContinuousEvidencePlaneError(
            "continuous evidence generation identifier mismatch"
        )
    lanes_raw = payload.get("scheduled_lanes")
    if not isinstance(lanes_raw, list) or any(not isinstance(item, str) for item in lanes_raw):
        raise ContinuousEvidencePlaneError("continuous evidence scheduled lanes are malformed")
    return EvidencePlaneGeneration(
        generation_id=generation_id,
        as_of=_parse_timestamp(payload.get("as_of"), field_name="evidence_plane_as_of"),
        completed_at=_parse_timestamp(
            payload.get("completed_at"), field_name="evidence_plane_completed_at"
        ),
        reference_manifest_id=str(payload.get("reference_manifest_id") or ""),
        scheduled_lanes=tuple(lanes_raw),
        historical_scope_count=int(payload.get("historical_scope_count", 0)),
        historical_coverage_digest=str(payload.get("historical_coverage_digest") or ""),
        public_live_state=str(payload.get("public_live_state") or ""),
    )


def _generation_qualified_for_cutoff(
    generation: EvidencePlaneGeneration | None,
    *,
    cutoff: datetime,
    max_age_seconds: float,
) -> bool:
    if generation is None:
        return False
    age = cutoff - generation.as_of
    return (
        timedelta(0) <= age <= timedelta(seconds=max_age_seconds)
        and generation.completed_at >= generation.as_of
        and bool(generation.reference_manifest_id)
        and bool(generation.historical_coverage_digest)
        and generation.public_live_state != "failed"
    )


def ensure_point_in_time_snapshot(
    *,
    cutoff: datetime | None = None,
    values: Mapping[str, str] | None = None,
    allow_refresh: bool = True,
) -> PointInTimeEvidenceSnapshot:
    """Freeze an integrity-bound evidence snapshot for one CIO decision cutoff."""

    resolved = dict(os.environ if values is None else values)
    if not evidence_plane_enabled(resolved):
        raise ContinuousEvidencePlaneError("continuous evidence plane is disabled")
    explicit_cutoff = cutoff is not None
    requested = _aware(
        datetime.now(timezone.utc) if cutoff is None else cutoff,
        field_name="snapshot_cutoff",
    )
    if requested > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ContinuousEvidencePlaneError("point-in-time snapshot cutoff is in the future")
    max_age = _max_age_seconds(resolved)

    generation = load_latest_evidence_plane(resolved)
    if not _generation_qualified_for_cutoff(
        generation,
        cutoff=requested,
        max_age_seconds=max_age,
    ):
        if not allow_refresh:
            raise ContinuousEvidencePlaneError(
                "continuous evidence plane is missing or stale for the CIO cutoff"
            )
        generation = refresh_continuous_evidence_plane(
            as_of=requested,
            values=resolved,
        )

    # On a cold bootstrap the first full preparation can legitimately take time. For an
    # unscheduled/manual decision, advance T after that preparation and perform one more
    # refresh only if the prepared plane aged beyond its SLA. With #631's persistent
    # history this second pass is a small delta rather than another historical rebuild.
    snapshot_cutoff = requested
    if not explicit_cutoff:
        current = datetime.now(timezone.utc)
        if generation is None:
            raise ContinuousEvidencePlaneError("continuous evidence plane did not qualify")
        if current - generation.as_of > timedelta(seconds=max_age):
            generation = refresh_continuous_evidence_plane(
                as_of=current,
                values=resolved,
            )
        snapshot_cutoff = current

    if generation is None or not _generation_qualified_for_cutoff(
        generation,
        cutoff=snapshot_cutoff,
        max_age_seconds=max_age,
    ):
        raise ContinuousEvidencePlaneError(
            "continuous evidence plane is not qualified for the final CIO cutoff"
        )

    snapshot_material = {
        "schema_version": _SNAPSHOT_SCHEMA,
        "release": _release(resolved),
        "cutoff": snapshot_cutoff.isoformat(),
        "plane_generation_id": generation.generation_id,
        "plane_as_of": generation.as_of.isoformat(),
        "reference_manifest_id": generation.reference_manifest_id,
        "historical_scope_count": generation.historical_scope_count,
        "historical_coverage_digest": generation.historical_coverage_digest,
        "scheduled_lanes": list(generation.scheduled_lanes),
        "raw_evidence_duplicated": False,
        "point_in_time_enforced": True,
        "investment_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    snapshot_id = _digest(snapshot_material)
    payload = dict(snapshot_material)
    payload["snapshot_id"] = snapshot_id
    path = (
        _root(resolved)
        / "snapshots"
        / _safe(_release(resolved))
        / f"{snapshot_cutoff.strftime('%Y%m%dT%H%M%S%fZ')}-{snapshot_id[:20]}.json"
    )
    _atomic_json(path, payload)
    return PointInTimeEvidenceSnapshot(
        snapshot_id=snapshot_id,
        cutoff=snapshot_cutoff,
        plane_generation_id=generation.generation_id,
        plane_as_of=generation.as_of,
        reference_manifest_id=generation.reference_manifest_id,
        historical_scope_count=generation.historical_scope_count,
        historical_coverage_digest=generation.historical_coverage_digest,
        path=path,
    )


__all__ = [
    "ContinuousEvidencePlaneError",
    "EvidencePlaneGeneration",
    "PointInTimeEvidenceSnapshot",
    "ensure_point_in_time_snapshot",
    "evidence_plane_enabled",
    "load_latest_evidence_plane",
    "refresh_continuous_evidence_plane",
]