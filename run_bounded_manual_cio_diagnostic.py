"""Runtime entrypoint for bounded CIO reference and evidence readiness.

Production release diagnostics consume an already-qualified exact-release evidence
generation. Expensive reference/public/discovery acquisition is owned by the continuous
evidence maintainer and never runs from this bounded CIO wrapper. The watchdog remains
fail-closed: if the immutable point-in-time generation or its current configuration-bound
reference manifest is unavailable, the CIO child is not started.

Non-production callers retain the historical reference-readiness fallback so tests and
local tooling without a persistent production evidence plane preserve their behavior.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, MutableMapping

import run_bounded_manual_cio_diagnostic_core as _core
from operations import manual_cio_diagnostic as _diagnostic_coordination
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


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _install_recovery_progress_contract() -> None:
    """Keep provider recovery telemetry from aborting the recovery it describes."""

    current = frozenset(getattr(_diagnostic_coordination, "_PROGRESS_METRICS", ()))
    if not _RECOVERY_PROGRESS_METRICS.issubset(current):
        _diagnostic_coordination._PROGRESS_METRICS = frozenset(
            (*current, *_RECOVERY_PROGRESS_METRICS)
        )


def _prime_forced_replacement(values: Mapping[str, str]) -> None:
    """Create retry coordination before reference readiness can fail again."""

    existing = latest_manual_cio_diagnostic(values=values)
    if existing is None or existing.state not in {"completed", "failed"}:
        return
    request_manual_cio_diagnostic(
        requested_by=f"render-release:{_release(values)}",
        values=values,
    )


def _production_plane_enabled(values: Mapping[str, str]) -> bool:
    explicit = values.get("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "").strip()
    production = (
        values.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "").strip().lower() == "production"
        or values.get("RENDER", "").strip().lower() == "true"
    )
    return (bool(explicit) or production) and evidence_plane_enabled(values)


def _configure_provider_free_consumer(values: MutableMapping[str, str]) -> bool:
    """Keep the production CIO child from initiating public/provider acquisition.

    Release evidence qualification happens in a separate bounded evidence-owner process
    before this watchdog is invoked.  The historical manual diagnostic still contains a
    forced public-collection call; disabling collection in the child environment makes
    that call a local no-op rather than an external provider transaction.  The evidence
    owner does not inherit this child-only environment mutation.
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
    install_cme_futures_reference_lineage()

    if _production_plane_enabled(values):
        if not isinstance(values, MutableMapping):
            raise TypeError(
                "production prequalified evidence requires a mutable watchdog environment"
            )
        # Disk/config validation only. This binds the exact manifest path/id into the
        # child environment after validating the current immutable evidence generation.
        # No reference/public/discovery provider acquisition is permitted here.
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


if __name__ == "__main__":
    _configure_provider_free_consumer(os.environ)
    if "--force" in sys.argv[1:]:
        _prime_forced_replacement(os.environ)
    raise SystemExit(_core.main())

# Preserve the historical import surface. Test and library imports of
# run_bounded_manual_cio_diagnostic receive the unchanged core module after the runtime
# provider injection above, so module-global monkeypatches continue to affect the core.
sys.modules[__name__] = _core
