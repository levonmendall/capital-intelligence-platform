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
from operations.capability_scoped_release_diagnostic import (
    capability_scoped_operation_enabled,
    load_capability_operating_reference_manifest,
)
from operations.cme_futures_reference_runtime import (
    install_cme_futures_reference_lineage,
)
from operations.continuous_evidence_plane import evidence_plane_enabled
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
from operations.reclaimable_memory_guard import (
    wait_with_reclaimable_resource_bounds,
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
_PROVIDER_FREE_CONSUMER_ENV = "CAPITAL_INTELLIGENCE_CIO_PROVIDER_FREE_CONSUMER"
_PUBLIC_COLLECTION_ENABLED_ENV = "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED"
_ORIGINAL_CONTAINER_MEMORY_KIB = _core._container_memory_kib
_ORIGINAL_CGROUP_MEMORY_KIB = _core._cgroup_memory_kib
_ORIGINAL_PROCESS_MEMORY_KIB = _core._process_memory_kib
_ORIGINAL_WAIT_WITH_RESOURCE_BOUNDS = _core._wait_with_resource_bounds


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
    """

    if (
        _core._cgroup_memory_kib is not _ORIGINAL_CGROUP_MEMORY_KIB
        or _core._process_memory_kib is not _ORIGINAL_PROCESS_MEMORY_KIB
    ):
        return _ORIGINAL_WAIT_WITH_RESOURCE_BOUNDS(process, **kwargs)
    return wait_with_reclaimable_resource_bounds(process, **kwargs)


def _install_recovery_progress_contract() -> None:
    """Keep provider recovery telemetry from aborting the recovery it describes."""

    current = frozenset(getattr(_diagnostic_coordination, "_PROGRESS_METRICS", ()))
    if not _RECOVERY_PROGRESS_METRICS.issubset(current):
        _diagnostic_coordination._PROGRESS_METRICS = frozenset(
            (*current, *_RECOVERY_PROGRESS_METRICS)
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
    # Capability-scoped Render is independently qualified by its operating evidence plane;
    # it must remain provider-free even when the comprehensive evidence plane is absent or
    # stale. Legacy full-discovery operation retains the original evidence-plane contract.
    if capability_scoped_operation_enabled(values):
        return True
    explicit = values.get("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "").strip()
    production = (
        values.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "").strip().lower() == "production"
        or values.get("RENDER", "").strip().lower() == "true"
    )
    return (bool(explicit) or production) and evidence_plane_enabled(values)


def _configure_provider_free_consumer(values: MutableMapping[str, str]) -> bool:
    """Keep the production CIO child from initiating public/provider acquisition.

    Evidence qualification happens in a separate bounded evidence-owner process before
    this watchdog is invoked. The historical manual diagnostic still contains a forced
    public-collection call; disabling collection in the child environment makes that call
    a local no-op rather than an external provider transaction. The evidence owner does not
    inherit this child-only environment mutation.
    """

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
        # Disk-only validation of the fresh immutable operating snapshot. The downstream
        # qualified-paper-evidence probe independently verifies the exact signed universe
        # and every requested structural subset before the CIO receives evidence.
        return load_capability_operating_reference_manifest(values)

    install_cme_futures_reference_lineage()
    if _production_plane_enabled(values):
        if not isinstance(values, MutableMapping):
            raise TypeError(
                "production prequalified evidence requires a mutable watchdog environment"
            )
        # Legacy full-discovery mode: bind the exact comprehensive reference manifest after
        # validating the current immutable evidence generation. No provider calls here.
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
# All bounded Render jobs import this wrapper before invoking the shared watchdog. Replace
# the legacy raw-memory kill test with the dual reclaimable-aware guard while preserving the
# watchdog's exact return contract, hard service-OOM boundary, and explicit injection seam.
_core._wait_with_resource_bounds = _wait_with_reclaimable_bounds


if __name__ == "__main__":
    _configure_provider_free_consumer(os.environ)
    if "--force" in sys.argv[1:]:
        _prime_forced_replacement(os.environ)
    raise SystemExit(_core.main())

# Preserve the historical import surface. Test and library imports of
# run_bounded_manual_cio_diagnostic receive the unchanged core module after the runtime
# provider injection above, so module-global monkeypatches continue to affect the core.
sys.modules[__name__] = _core
