"""Runtime entrypoint for bounded CIO reference and evidence readiness.

Production release diagnostics consume already-qualified immutable evidence. In
capability-scoped operation the watchdog validates the independent operating-evidence
snapshot rather than requiring a comprehensive all-market evidence generation. Legacy
full-discovery mode retains the historical exact-release reference-manifest gate.

Expensive reference/public/discovery acquisition is never owned by this bounded CIO
wrapper. Missing or stale authority remains fail-closed and the CIO child remains a
provider-free consumer in production.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, MutableMapping

import run_bounded_manual_cio_diagnostic_core as _core
from operations import manual_cio_diagnostic as _diagnostic_coordination
from operations import reclaimable_memory_guard as _reclaimable_guard
from operations.capability_scoped_release_diagnostic import (
    capability_scoped_operation_enabled,
    load_capability_operating_reference_manifest,
)
from operations.cme_futures_reference_runtime import (
    install_cme_futures_reference_lineage,
)
from operations.continuous_evidence_plane import evidence_plane_enabled
from operations.evidence_file_cache_release import (
    release_completed_operating_evidence_file_cache,
)
from operations.generalized_reference_readiness import (
    prepare_reference_readiness as _prepare_reference,
)
from operations.manual_cio_diagnostic import (
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)
from operations.qualified_evidence_maintenance import (
    load_prequalified_reference_manifest,
)
from operations.streaming_file_cache_reclamation import (
    release_streaming_clean_file_cache,
)
from providers.cme_futures_reference_executable import (
    CmeExecutableFuturesReferenceProvider,
)
from providers.massive_futures_reference_rate_resilient import (
    MassiveFuturesReferenceProvider,
)

_RECOVERY_PROGRESS_METRICS = frozenset(
    {
        "recovery_exchanges",
        "recovered_exchanges",
    }
)
_PRODUCTION_CONTEXT_PROGRESS_STAGES = frozenset(
    {
        "production_context_holding_marks_started",
        "production_context_holding_marks_failed",
    }
)
_PROVIDER_FREE_CONSUMER_ENV = "CAPITAL_INTELLIGENCE_CIO_PROVIDER_FREE_CONSUMER"
_PUBLIC_COLLECTION_ENABLED_ENV = "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED"
_ORIGINAL_CONTAINER_MEMORY_KIB = _core._container_memory_kib
_ORIGINAL_CGROUP_MEMORY_KIB = _core._cgroup_memory_kib
_ORIGINAL_PROCESS_MEMORY_KIB = _core._process_memory_kib
_ORIGINAL_WAIT_WITH_RESOURCE_BOUNDS = _core._wait_with_resource_bounds
_core._last_reclaimable_memory_report = None


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _container_memory_with_configured_ceiling(
    values: Mapping[str, str],
) -> tuple[int | None, int | None, str]:
    """Never let a loose host cgroup override the governed service-memory quota."""

    current_kib, observed_limit_kib, source = _ORIGINAL_CONTAINER_MEMORY_KIB(values)
    configured_limit_kib = _core._configured_memory_limit_kib(values)
    if (
        current_kib is not None
        and observed_limit_kib is not None
        and configured_limit_kib is not None
        and configured_limit_kib < observed_limit_kib
    ):
        return (
            current_kib,
            configured_limit_kib,
            f"{source}_configured_ceiling",
        )
    return current_kib, observed_limit_kib, source


def _wait_with_reclaimable_bounds(process, **kwargs):
    """Use the production dual guard while preserving explicit accounting injection.

    The historical watchdog exposes cgroup/process readers as a deliberate test and
    integration seam. If a caller replaces either reader, honor that injected accounting
    with the original conservative watchdog instead of mixing synthetic raw counters with
    live ``memory.stat`` from another cgroup. Normal production keeps the original readers
    and therefore always uses the reclaimable-aware dual guard.

    When cgroup-v2 ``memory.reclaim`` exists but cannot actually reclaim the raw-only file
    cache, make one bounded streaming clean-file pass before the unchanged hard ceiling is
    allowed to terminate the child. The fallback is attempted only for raw-only pressure,
    never working-set pressure, and cannot change any resource boundary.

    The guard's credential-safe trigger/peak record is also retained on the shared core
    module for the caller that owns the bounded child. This does not alter the historical
    five-value wait contract, so every existing worker remains compatible while release
    telemetry can distinguish real working-set pressure from the independent raw hard cap.
    """

    if (
        _core._cgroup_memory_kib is not _ORIGINAL_CGROUP_MEMORY_KIB
        or _core._process_memory_kib is not _ORIGINAL_PROCESS_MEMORY_KIB
    ):
        result = _ORIGINAL_WAIT_WITH_RESOURCE_BOUNDS(process, **kwargs)
        _core._last_reclaimable_memory_report = {
            "memory_limited": bool(result[2]),
            "trigger_reason": "legacy_accounting" if result[2] else None,
            "credential_safe": True,
        }
        return result

    captured: dict[str, object] = {}
    original_log = _reclaimable_guard._safe_log
    original_reclaim = _reclaimable_guard._attempt_cgroup_v2_reclaim
    fallback_used = False

    def capture(event: str, **details: object) -> None:
        if event == "reclaimable_memory_guard_triggered":
            captured.update(details)
            captured["triggered"] = True
        elif event == "reclaimable_memory_guard_finished":
            captured.update(details)
            captured["finished"] = True
        elif event == "reclaimable_memory_guard_file_cache_fallback":
            captured.update(details)
            captured["file_cache_fallback_observed"] = True
        original_log(event, **details)

    def reclaim_with_file_cache_fallback(snapshot, boundaries, *, values):
        nonlocal fallback_used
        result, after = original_reclaim(snapshot, boundaries, values=values)
        reason = _reclaimable_guard.limit_reason(after, boundaries)
        should_fallback = (
            not fallback_used
            and reason == "raw_hard_ceiling"
            and (
                result.error_type is not None
                or not result.supported
                or result.reclaimed_kib < _reclaimable_guard._RAW_RECLAIM_MIN_PROGRESS_KIB
            )
        )
        if not should_fallback:
            return result, after

        fallback_used = True
        fallback_error_type: str | None = None
        try:
            report = release_streaming_clean_file_cache(values)
        except Exception as error:  # noqa: BLE001 - operational fallback stays fail-soft.
            report = {}
            fallback_error_type = type(error).__name__
        fallback_after = _reclaimable_guard.memory_snapshot(values)
        before_raw = after.raw_current_kib
        after_raw = fallback_after.raw_current_kib
        fallback_reclaimed = (
            max(0, int(before_raw) - int(after_raw))
            if isinstance(before_raw, int) and isinstance(after_raw, int)
            else 0
        )
        net_reclaimed = (
            max(0, int(result.raw_before_kib) - int(after_raw))
            if isinstance(result.raw_before_kib, int) and isinstance(after_raw, int)
            else result.reclaimed_kib + fallback_reclaimed
        )
        fallback_effective = (
            _reclaimable_guard.limit_reason(fallback_after, boundaries) is None
        )
        capture(
            "reclaimable_memory_guard_file_cache_fallback",
            memory_reclaim_operable=bool(result.supported and result.error_type is None),
            memory_cgroup_reclaim_error_type=result.error_type,
            memory_file_cache_fallback_attempted=True,
            memory_file_cache_fallback_supported=bool(report.get("supported")),
            memory_file_cache_fallback_scan_entries=report.get("scan_entries"),
            memory_file_cache_fallback_released_file_count=report.get(
                "released_file_count"
            ),
            memory_file_cache_fallback_released_bytes=report.get("released_bytes"),
            memory_file_cache_fallback_raw_before_kib=before_raw,
            memory_file_cache_fallback_raw_after_kib=after_raw,
            memory_file_cache_fallback_reclaimed_kib=fallback_reclaimed,
            memory_file_cache_fallback_effective=fallback_effective,
            memory_file_cache_fallback_error_type=fallback_error_type,
            working_set_boundary_kib=boundaries.working_set_kib,
            raw_hard_boundary_kib=boundaries.raw_hard_kib,
        )
        return (
            _reclaimable_guard.MemoryReclaimResult(
                attempted=result.attempted or bool(report.get("selected_file_count")),
                supported=bool(result.supported and result.error_type is None),
                requested_kib=result.requested_kib,
                raw_before_kib=result.raw_before_kib,
                raw_after_kib=after_raw,
                working_set_before_kib=result.working_set_before_kib,
                working_set_after_kib=fallback_after.working_set_kib,
                reclaimed_kib=net_reclaimed,
                effective=fallback_effective,
                error_type=None if fallback_effective else result.error_type,
            ),
            fallback_after,
        )

    _reclaimable_guard._safe_log = capture
    _reclaimable_guard._attempt_cgroup_v2_reclaim = reclaim_with_file_cache_fallback
    try:
        result = _reclaimable_guard.wait_with_reclaimable_resource_bounds(
            process,
            **kwargs,
        )
    finally:
        _reclaimable_guard._attempt_cgroup_v2_reclaim = original_reclaim
        _reclaimable_guard._safe_log = original_log
    captured.setdefault("memory_limited", bool(result[2]))
    captured.setdefault("credential_safe", True)
    _core._last_reclaimable_memory_report = dict(captured)
    return result


def _install_recovery_progress_contract() -> None:
    """Keep valid runtime progress telemetry from aborting the work it describes."""

    current_metrics = frozenset(getattr(_diagnostic_coordination, "_PROGRESS_METRICS", ()))
    if not _RECOVERY_PROGRESS_METRICS.issubset(current_metrics):
        _diagnostic_coordination._PROGRESS_METRICS = frozenset(
            (*current_metrics, *_RECOVERY_PROGRESS_METRICS)
        )

    current_stages = frozenset(getattr(_diagnostic_coordination, "_PROGRESS_STAGES", ()))
    if not _PRODUCTION_CONTEXT_PROGRESS_STAGES.issubset(current_stages):
        _diagnostic_coordination._PROGRESS_STAGES = frozenset(
            (*current_stages, *_PRODUCTION_CONTEXT_PROGRESS_STAGES)
        )


def _prime_forced_replacement(values: Mapping[str, str]) -> None:
    """Create retry coordination before readiness can fail again."""

    existing = latest_manual_cio_diagnostic(values=values)
    if existing is None or existing.state not in {"completed", "failed"}:
        return
    request_manual_cio_diagnostic(
        requested_by=f"render-release:{_release(values)}",
        values=values,
    )


def _production_plane_enabled(values: Mapping[str, str]) -> bool:
    if capability_scoped_operation_enabled(values):
        return True
    explicit = values.get("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "").strip()
    production = (
        values.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "").strip().lower() == "production"
        or values.get("RENDER", "").strip().lower() == "true"
    )
    return (bool(explicit) or production) and evidence_plane_enabled(values)


def _configure_provider_free_consumer(values: MutableMapping[str, str]) -> bool:
    """Keep the production CIO child from initiating public/provider acquisition."""

    if not _production_plane_enabled(values):
        return False
    values[_PROVIDER_FREE_CONSUMER_ENV] = "true"
    values[_PUBLIC_COLLECTION_ENABLED_ENV] = "false"
    return True


def _prepare_with_rate_budget(
    values: Mapping[str, str],
    **kwargs: object,
):
    _install_recovery_progress_contract()

    if capability_scoped_operation_enabled(values):
        if not isinstance(values, MutableMapping):
            raise TypeError(
                "capability operating evidence requires a mutable watchdog environment"
            )
        manifest = load_capability_operating_reference_manifest(values)
        release_completed_operating_evidence_file_cache(values)
        return manifest

    install_cme_futures_reference_lineage()
    if _production_plane_enabled(values):
        if not isinstance(values, MutableMapping):
            raise TypeError(
                "production prequalified evidence requires a mutable watchdog environment"
            )
        return load_prequalified_reference_manifest(values)

    kwargs.setdefault(
        "massive_futures_provider",
        CmeExecutableFuturesReferenceProvider(
            fallback_provider=MassiveFuturesReferenceProvider(),
            values=values,
        ),
    )
    return _prepare_reference(values, **kwargs)


_install_recovery_progress_contract()
_core.prepare_reference_readiness = _prepare_with_rate_budget
_core._prime_forced_replacement = _prime_forced_replacement
_core._container_memory_kib = _container_memory_with_configured_ceiling
_core._wait_with_resource_bounds = _wait_with_reclaimable_bounds


if __name__ == "__main__":
    _configure_provider_free_consumer(os.environ)
    if "--force" in sys.argv[1:]:
        _prime_forced_replacement(os.environ)
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
