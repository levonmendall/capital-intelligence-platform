"""Maintain evidence from release-independent components before provider acquisition.

The continuous evidence plane is the reusable market-information boundary. Application
releases bind to already-qualified components; they do not make those components
release-specific. Fresh prior-release evidence can therefore be rebound to a new release
without provider calls only when every reusable component still satisfies its own
freshness and compatibility contract.

Reference readiness uses the existing lane-component store. Required public-live
information uses the generic qualified component ledger so a successful collection is
committed immediately and survives a later discovery failure or outer qualification
retry. Missing, stale, corrupt, configuration-mismatched, or incomplete components
remain fail-closed and are selectively reacquired.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping

from operations import continuous_evidence_plane as _plane
from operations import qualified_evidence_ledger as _ledger
from operations import qualified_evidence_maintenance as _legacy_maintenance
from operations.qualified_evidence_maintenance import EvidenceMaintenanceResult
from operations.reference_readiness import ReferenceReadinessError
from operations.release_reference_binding import bind_reference_manifest_from_components


_PUBLIC_COMPONENT = "required-public-live"
_PUBLIC_COMPONENT_CONTRACT = "required-public-live.v1"
_PUBLIC_COMPATIBILITY_FILES = (
    "config/public_live_information_sources.json",
    "providers/public_live_information.py",
    "public_live_collection_runtime.py",
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


def _public_component_compatibility() -> str:
    """Fingerprint the governed public-source contract without binding it to a release."""

    repository_root = Path(__file__).resolve().parents[1]
    material: list[object] = [_PUBLIC_COMPONENT_CONTRACT]
    for relative in _PUBLIC_COMPATIBILITY_FILES:
        path = repository_root / relative
        try:
            material.append((relative, path.read_text(encoding="utf-8")))
        except OSError as error:
            raise _plane.ContinuousEvidencePlaneError(
                f"public evidence compatibility input is unavailable: {relative}"
            ) from error
    return _ledger.compatibility_fingerprint(*material)


def _load_public_component(
    values: Mapping[str, str],
    *,
    cutoff: datetime,
):
    try:
        return _ledger.load_qualified_component(
            values=values,
            component_name=_PUBLIC_COMPONENT,
            compatibility=_public_component_compatibility(),
            cutoff=cutoff,
        )
    except _ledger.QualifiedEvidenceLedgerError as error:
        raise _plane.ContinuousEvidencePlaneError(
            f"qualified public evidence component is invalid: {error}"
        ) from error


def _component_public_collector(
    values: Mapping[str, str],
) -> Callable[[datetime], object]:
    """Reuse a compatible public component or acquire and commit exactly one new one."""

    compatibility = _public_component_compatibility()

    def collect(timestamp: datetime):
        try:
            cached = _ledger.load_qualified_component(
                values=values,
                component_name=_PUBLIC_COMPONENT,
                compatibility=compatibility,
                cutoff=timestamp,
            )
        except _ledger.QualifiedEvidenceLedgerError as error:
            raise _plane.ContinuousEvidencePlaneError(
                f"qualified public evidence component is invalid: {error}"
            ) from error
        if cached is not None:
            state = str(cached.payload.get("state") or "available")
            return SimpleNamespace(
                state=state,
                required_sources_ready=True,
                failed_required_source_identifiers=(),
                collection_scope=str(cached.payload.get("collection_scope") or "required"),
                qualified_component_id=cached.component_id,
                qualified_component_reused=True,
            )

        result = _legacy_maintenance._default_public_collector(timestamp)
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
        # Preserve the source evidence cutoff. Exact-release rebinding changes code
        # lineage, not the point in time at which the reusable evidence was observed.
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
    }
    if reference_manifest is not None:
        kwargs["reference_preparer"] = (
            lambda _values, prepared=reference_manifest: prepared
        )
    return _legacy_maintenance.maintain_continuous_evidence_plane(**kwargs)


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

    # Fast path 1: the current release already owns a complete fresh generation. The
    # disk-only loader revalidates the exact manifest and snapshot with no provider work.
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

    # Fast path 2: previous-release evidence may be rebound only when both the reference
    # components and the public-live component still satisfy their current contracts.
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

    # The composite generation needs refresh. Bind release-independent references from
    # disk first. Public evidence is independently reused/committed by _legacy_refresh,
    # so a later discovery failure no longer forces another public provider sweep.
    mutable = dict(resolved)
    try:
        manifest = bind_reference_manifest_from_components(mutable, now=requested)
    except ReferenceReadinessError:
        return _legacy_refresh(requested=requested, values=resolved)

    return _legacy_refresh(
        requested=requested,
        values=resolved,
        reference_manifest=manifest,
    )


__all__ = ["maintain_component_qualified_evidence_plane"]
