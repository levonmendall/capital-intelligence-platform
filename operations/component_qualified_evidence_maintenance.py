"""Maintain evidence from release-independent components before provider acquisition.

The continuous evidence plane is the reusable market-information boundary. Application
releases bind to already-qualified components; they do not make those components
release-specific. Fresh prior-release evidence can therefore be rebound to a new release
without provider calls only when every reusable component still satisfies its own
freshness and compatibility contract.

Reference readiness uses the existing lane-component store. Required public-live,
comprehensive-discovery, and historical-coverage evidence use the generic qualified
component ledger. Successful components are committed immediately and a later failure
resumes the same still-fresh evidence epoch instead of restarting the whole plane.
Missing, stale, corrupt, configuration-mismatched, or incomplete components remain
fail-closed and are selectively reacquired.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping

from operations import continuous_evidence_plane as _plane
from operations import qualified_evidence_ledger as _ledger
from operations import qualified_evidence_maintenance as _legacy_maintenance
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    load_qualified_comprehensive_discovery_snapshot,
)
from operations.qualified_evidence_maintenance import EvidenceMaintenanceResult
from operations.reference_readiness import ReferenceReadinessError
from operations.release_reference_binding import bind_reference_manifest_from_components


_PUBLIC_COMPONENT = "required-public-live"
_PUBLIC_COMPONENT_CONTRACT = "required-public-live.v2"
_PUBLIC_COMPATIBILITY_FILES = (
    "config/public_live_information_sources.json",
    "providers/public_live_information.py",
    "public_live_collection_runtime.py",
)
_DISCOVERY_COMPONENT = "comprehensive-discovery"
_DISCOVERY_COMPONENT_CONTRACT = "comprehensive-discovery.v1"
_DISCOVERY_COMPATIBILITY_FILES = (
    "config/comprehensive_market_discovery.json",
    "operations/comprehensive_market_discovery.py",
    "operations/_comprehensive_market_discovery_v6.py",
    "operations/comprehensive_discovery_snapshot.py",
    "operations/qualified_comprehensive_discovery_snapshot.py",
)
_HISTORY_COMPONENT = "historical-coverage"
_HISTORY_COMPONENT_CONTRACT = "historical-coverage.v1"
_HISTORY_COMPATIBILITY_FILES = (
    "operations/persistent_historical_evidence.py",
    "operations/continuous_evidence_plane.py",
)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _latest_payload(values: Mapping[str, str]) -> Mapping[str, object] | None:
    return _plane._read_integrity_json(
        _plane._root(values) / "latest-qualified.json",
        schema=_plane._PLANE_SCHEMA,
    )


def _compatibility_fingerprint(
    *,
    contract: str,
    files: tuple[str, ...],
    label: str,
) -> str:
    repository_root = Path(__file__).resolve().parents[1]
    material: list[object] = [contract]
    for relative in files:
        path = repository_root / relative
        try:
            material.append((relative, path.read_text(encoding="utf-8")))
        except OSError as error:
            raise _plane.ContinuousEvidencePlaneError(
                f"{label} evidence compatibility input is unavailable: {relative}"
            ) from error
    return _ledger.compatibility_fingerprint(*material)


def _public_component_compatibility() -> str:
    return _compatibility_fingerprint(
        contract=_PUBLIC_COMPONENT_CONTRACT,
        files=_PUBLIC_COMPATIBILITY_FILES,
        label="public",
    )


def _discovery_component_compatibility() -> str:
    return _compatibility_fingerprint(
        contract=_DISCOVERY_COMPONENT_CONTRACT,
        files=_DISCOVERY_COMPATIBILITY_FILES,
        label="discovery",
    )


def _history_component_compatibility() -> str:
    return _compatibility_fingerprint(
        contract=_HISTORY_COMPONENT_CONTRACT,
        files=_HISTORY_COMPATIBILITY_FILES,
        label="historical",
    )


def _load_component(
    values: Mapping[str, str],
    *,
    component_name: str,
    compatibility: str,
    cutoff: datetime,
    label: str,
):
    try:
        return _ledger.load_qualified_component(
            values=values,
            component_name=component_name,
            compatibility=compatibility,
            cutoff=cutoff,
        )
    except _ledger.QualifiedEvidenceLedgerError as error:
        raise _plane.ContinuousEvidencePlaneError(
            f"qualified {label} evidence component is invalid: {error}"
        ) from error


def _load_public_component(
    values: Mapping[str, str],
    *,
    cutoff: datetime,
):
    return _load_component(
        values,
        component_name=_PUBLIC_COMPONENT,
        compatibility=_public_component_compatibility(),
        cutoff=cutoff,
        label="public",
    )


def _load_exact_component(
    values: Mapping[str, str],
    *,
    component_name: str,
    compatibility: str,
    evidence_as_of: datetime,
    label: str,
):
    component = _load_component(
        values,
        component_name=component_name,
        compatibility=compatibility,
        cutoff=datetime.now(timezone.utc),
        label=label,
    )
    if component is None or component.as_of != _aware(
        evidence_as_of,
        field_name=f"{label}_evidence_as_of",
    ):
        return None
    return component


def _component_public_collector(
    values: Mapping[str, str],
) -> Callable[[datetime], object]:
    """Reuse a public qualification for the same epoch or across a release rebind."""

    compatibility = _public_component_compatibility()

    def collect(timestamp: datetime):
        evidence_as_of = _aware(timestamp, field_name="public_evidence_as_of")
        cached = _load_component(
            values,
            component_name=_PUBLIC_COMPONENT,
            compatibility=compatibility,
            cutoff=datetime.now(timezone.utc),
            label="public",
        )
        if cached is not None and (
            cached.as_of == evidence_as_of
            or cached.observed_release != _release(values)
        ):
            state = str(cached.payload.get("state") or "available")
            return SimpleNamespace(
                state=state,
                required_sources_ready=True,
                failed_required_source_identifiers=(),
                collection_scope=str(cached.payload.get("collection_scope") or "required"),
                qualified_component_id=cached.component_id,
                qualified_component_reused=True,
            )

        result = _legacy_maintenance._default_public_collector(evidence_as_of)
        state = str(getattr(result, "state", "available")).strip().lower() or "available"
        if getattr(result, "required_sources_ready", None) is not True:
            raise _plane.ContinuousEvidencePlaneError(
                "required public live information did not qualify before component commit"
            )
        try:
            component = _ledger.publish_qualified_component(
                values=values,
                component_name=_PUBLIC_COMPONENT,
                compatibility=compatibility,
                as_of=evidence_as_of,
                payload={
                    "state": state,
                    "required_sources_ready": True,
                    "collection_scope": str(
                        getattr(result, "collection_scope", "required") or "required"
                    ),
                },
            )
        except _ledger.QualifiedEvidenceLedgerError as error:
            raise _plane.ContinuousEvidencePlaneError(
                f"qualified public evidence component cannot be committed: {error}"
            ) from error
        try:
            setattr(result, "qualified_component_id", component.component_id)
            setattr(result, "qualified_component_reused", False)
        except (AttributeError, TypeError):
            pass
        return result

    return collect


def _publish_history_component(
    values: Mapping[str, str],
    *,
    evidence_as_of: datetime,
    scope_count: int,
    coverage_digest: str,
):
    try:
        return _ledger.publish_qualified_component(
            values=values,
            component_name=_HISTORY_COMPONENT,
            compatibility=_history_component_compatibility(),
            as_of=evidence_as_of,
            payload={
                "historical_scope_count": int(scope_count),
                "historical_coverage_digest": str(coverage_digest),
            },
        )
    except _ledger.QualifiedEvidenceLedgerError as error:
        raise _plane.ContinuousEvidencePlaneError(
            f"qualified historical evidence component cannot be committed: {error}"
        ) from error


def _component_discovery_runner(
    values: Mapping[str, str],
) -> Callable[[datetime], object]:
    """Reuse an exact discovery/history checkpoint or commit both after one success."""

    discovery_compatibility = _discovery_component_compatibility()
    history_compatibility = _history_component_compatibility()

    def run(timestamp: datetime):
        evidence_as_of = _aware(timestamp, field_name="discovery_evidence_as_of")
        cached_discovery = _load_exact_component(
            values,
            component_name=_DISCOVERY_COMPONENT,
            compatibility=discovery_compatibility,
            evidence_as_of=evidence_as_of,
            label="discovery",
        )
        if cached_discovery is not None:
            try:
                snapshot = load_qualified_comprehensive_discovery_snapshot(
                    evidence_as_of=evidence_as_of,
                    values=values,
                )
            except ComprehensiveDiscoverySnapshotError as error:
                raise _plane.ContinuousEvidencePlaneError(
                    f"qualified discovery component lost its immutable snapshot: {error}"
                ) from error
            if str(cached_discovery.payload.get("snapshot_id") or "") != snapshot.snapshot_id:
                raise _plane.ContinuousEvidencePlaneError(
                    "qualified discovery component snapshot identifier changed"
                )
            scope_count, coverage_digest = _plane._historical_coverage_summary(
                values,
                as_of=evidence_as_of,
            )
            cached_history = _load_exact_component(
                values,
                component_name=_HISTORY_COMPONENT,
                compatibility=history_compatibility,
                evidence_as_of=evidence_as_of,
                label="historical",
            )
            if (
                cached_history is None
                or int(cached_history.payload.get("historical_scope_count", -1)) != scope_count
                or str(cached_history.payload.get("historical_coverage_digest") or "")
                != coverage_digest
            ):
                _publish_history_component(
                    values,
                    evidence_as_of=evidence_as_of,
                    scope_count=scope_count,
                    coverage_digest=coverage_digest,
                )
            return snapshot.result

        result = _plane._default_discovery(evidence_as_of)
        try:
            snapshot = load_qualified_comprehensive_discovery_snapshot(
                evidence_as_of=evidence_as_of,
                values=values,
            )
        except ComprehensiveDiscoverySnapshotError as error:
            raise _plane.ContinuousEvidencePlaneError(
                f"comprehensive discovery did not publish its immutable snapshot: {error}"
            ) from error
        scope_count, coverage_digest = _plane._historical_coverage_summary(
            values,
            as_of=evidence_as_of,
        )
        try:
            _ledger.publish_qualified_component(
                values=values,
                component_name=_DISCOVERY_COMPONENT,
                compatibility=discovery_compatibility,
                as_of=evidence_as_of,
                payload={
                    "snapshot_id": snapshot.snapshot_id,
                    "scheduled_lanes": list(_plane._scheduled_lanes(evidence_as_of)),
                },
            )
        except _ledger.QualifiedEvidenceLedgerError as error:
            raise _plane.ContinuousEvidencePlaneError(
                f"qualified discovery evidence component cannot be committed: {error}"
            ) from error
        _publish_history_component(
            values,
            evidence_as_of=evidence_as_of,
            scope_count=scope_count,
            coverage_digest=coverage_digest,
        )
        return result

    return run


def _generation_base_qualified(
    generation: _plane.EvidencePlaneGeneration | None,
    *,
    values: Mapping[str, str],
    cutoff: datetime,
) -> bool:
    if generation is None:
        return False
    timestamp = _aware(cutoff, field_name="component_qualification_cutoff")
    age = timestamp - generation.as_of
    return bool(
        timedelta(0) <= age <= timedelta(seconds=_plane._max_age_seconds(values))
        and generation.completed_at >= generation.as_of
        and generation.historical_coverage_digest
        and generation.public_live_state not in {"failed", "disabled"}
        and tuple(generation.scheduled_lanes) == tuple(_plane._scheduled_lanes(timestamp))
    )


def _publish_release_rebind(
    *,
    values: Mapping[str, str],
    source: _plane.EvidencePlaneGeneration,
    reference_manifest_id: str,
) -> _plane.EvidencePlaneGeneration:
    """Bind fresh reusable evidence to a new release without claiming newer evidence."""

    completed = datetime.now(timezone.utc)
    material: dict[str, object] = {
        "schema_version": _plane._PLANE_SCHEMA,
        "release": _release(values),
        "as_of": source.as_of.isoformat(),
        "completed_at": completed.isoformat(),
        "reference_manifest_id": reference_manifest_id,
        "scheduled_lanes": list(source.scheduled_lanes),
        "historical_scope_count": source.historical_scope_count,
        "historical_coverage_digest": source.historical_coverage_digest,
        "public_live_state": source.public_live_state,
        "comprehensive_discovery_complete": True,
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    generation_id = _plane._digest(material)
    _plane._atomic_json(
        _plane._root(values) / "latest-qualified.json",
        {**material, "generation_id": generation_id},
    )
    return _plane.EvidencePlaneGeneration(
        generation_id=generation_id,
        as_of=source.as_of,
        completed_at=completed,
        reference_manifest_id=reference_manifest_id,
        scheduled_lanes=source.scheduled_lanes,
        historical_scope_count=source.historical_scope_count,
        historical_coverage_digest=source.historical_coverage_digest,
        public_live_state=source.public_live_state,
    )


def _legacy_refresh(
    *,
    requested: datetime,
    values: Mapping[str, str],
    reference_manifest: object | None = None,
) -> EvidenceMaintenanceResult:
    kwargs: dict[str, object] = {
        "as_of": requested,
        "values": values,
        "public_collector": _component_public_collector(values),
        "discovery": _component_discovery_runner(values),
    }
    if reference_manifest is not None:
        kwargs["reference_preparer"] = (
            lambda _values, prepared=reference_manifest: prepared
        )
    return _legacy_maintenance.maintain_continuous_evidence_plane(**kwargs)


def _resumable_evidence_cutoff(
    values: Mapping[str, str],
    *,
    requested: datetime,
) -> datetime:
    """Resume a still-fresh incomplete epoch instead of discarding qualified work."""

    public = _load_public_component(values, cutoff=requested)
    if public is None or public.as_of > requested:
        return requested
    return public.as_of


def maintain_component_qualified_evidence_plane(
    *,
    as_of: datetime | None = None,
    values: Mapping[str, str] | None = None,
) -> EvidenceMaintenanceResult:
    """Prefer qualified component reuse; acquire only components that actually need it."""

    resolved = dict(__import__("os").environ if values is None else values)
    requested = _aware(
        datetime.now(timezone.utc) if as_of is None else as_of,
        field_name="component_qualified_evidence_as_of",
    )
    if not _plane.evidence_plane_enabled(resolved):
        raise _plane.ContinuousEvidencePlaneError("continuous evidence plane is disabled")

    current = _plane.load_latest_evidence_plane(resolved)
    payload = _latest_payload(resolved)
    current_release = (
        str(payload.get("release") or "").strip()
        if isinstance(payload, Mapping)
        else ""
    )

    if (
        current is not None
        and current_release == _release(resolved)
        and _generation_base_qualified(current, values=resolved, cutoff=requested)
    ):
        mutable = dict(resolved)
        manifest = _legacy_maintenance.load_prequalified_reference_manifest(mutable)
        if manifest.manifest_id != current.reference_manifest_id:
            raise _plane.ContinuousEvidencePlaneError(
                "current evidence generation changed its reference binding"
            )
        archive = _legacy_maintenance._archive_generation(resolved, current)
        return EvidenceMaintenanceResult(
            generation=current,
            state="current",
            refreshed=False,
            preparation_passes=0,
            archived_generation_path=archive,
        )

    if (
        current is not None
        and current_release
        and current_release != _release(resolved)
        and _generation_base_qualified(current, values=resolved, cutoff=requested)
        and _load_public_component(resolved, cutoff=requested) is not None
    ):
        mutable = dict(resolved)
        try:
            manifest = bind_reference_manifest_from_components(
                mutable,
                now=current.as_of,
            )
        except ReferenceReadinessError:
            manifest = None
        if manifest is not None:
            rebound = _publish_release_rebind(
                values=resolved,
                source=current,
                reference_manifest_id=manifest.manifest_id,
            )
            archive = _legacy_maintenance._archive_generation(resolved, rebound)
            return EvidenceMaintenanceResult(
                generation=rebound,
                state="release_rebound",
                refreshed=False,
                preparation_passes=0,
                archived_generation_path=archive,
            )

    preparation_cutoff = _resumable_evidence_cutoff(resolved, requested=requested)
    mutable = dict(resolved)
    try:
        manifest = bind_reference_manifest_from_components(
            mutable,
            now=preparation_cutoff,
        )
    except ReferenceReadinessError:
        return _legacy_refresh(requested=preparation_cutoff, values=resolved)

    return _legacy_refresh(
        requested=preparation_cutoff,
        values=resolved,
        reference_manifest=manifest,
    )


__all__ = ["maintain_component_qualified_evidence_plane"]
