"""Runtime entrypoint for bounded CIO reference and evidence readiness.

The watchdog core stays unchanged. This entrypoint injects generalized persistent
reference readiness plus the governed CME-primary futures reference provider. Massive is
retained only as a bounded secondary fallback. In the production service it also
qualifies the continuous evidence plane before the bounded CIO child starts, so a cold
historical bootstrap cannot consume the CIO's 30-minute analysis deadline. Imported
callers receive the core module so existing tests and monkeypatches keep their behavior.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

import run_bounded_manual_cio_diagnostic_core as _core
from operations import manual_cio_diagnostic as _diagnostic_coordination
from operations.cme_futures_reference_runtime import (
    install_cme_futures_reference_lineage,
)
from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
    refresh_continuous_evidence_plane,
)
from operations.generalized_reference_readiness import (
    prepare_reference_readiness as _prepare_reference,
)
from operations.manual_cio_diagnostic import (
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)
from providers.cme_futures_reference_executable import (
    CmeExecutableFuturesReferenceProvider,
)
from providers.massive_futures_reference_rate_resilient import (
    MassiveFuturesReferenceProvider,
)

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_REFERENCE_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_RECOVERY_PROGRESS_METRICS = frozenset(
    {
        "recovery_exchanges",
        "recovered_exchanges",
    }
)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _install_recovery_progress_contract() -> None:
    """Keep provider recovery telemetry from aborting the recovery it describes.

    The bounded EODHD directory path emits recovery_exchanges/recovered_exchanges when
    parallel directory reads fall back to bounded serial recovery. Those are safe,
    nonnegative operational counters and must be accepted by the release diagnostic's
    credential-safe progress contract.
    """

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


def _restore_environment(prior: Mapping[str, str | None]) -> None:
    for name, value in prior.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _prepare_with_rate_budget(
    values: Mapping[str, str],
    **kwargs: object,
):
    _install_recovery_progress_contract()
    install_cme_futures_reference_lineage()
    kwargs.setdefault(
        "massive_futures_provider",
        CmeExecutableFuturesReferenceProvider(
            fallback_provider=MassiveFuturesReferenceProvider(),
            values=values,
        ),
    )
    manifest = _prepare_reference(values, **kwargs)
    if not _production_plane_enabled(values):
        return manifest

    manifest_path = values.get(_REFERENCE_MANIFEST_PATH_ENV, "").strip()
    manifest_id = values.get(_REFERENCE_MANIFEST_ID_ENV, "").strip()
    qualified_manifest_id = str(getattr(manifest, "manifest_id", "")).strip()
    if not manifest_path or not manifest_id:
        raise ContinuousEvidencePlaneError(
            "qualified reference readiness did not bind its manifest for evidence discovery"
        )
    if not qualified_manifest_id or qualified_manifest_id != manifest_id:
        raise ContinuousEvidencePlaneError(
            "qualified reference manifest identity changed before evidence discovery"
        )

    # Comprehensive discovery is itself used to populate the evidence plane. Mark this
    # pre-clock preparation so the discovery facade does not recursively request a
    # snapshot while the snapshot is being built. Discovery ultimately resolves the
    # governed reference manifest from os.environ, while the watchdog carries readiness
    # state in its own values dictionary. Bind the exact qualified path/id into the
    # process environment for this preparation only, and make the evidence refresh reuse
    # the already-qualified manifest instead of performing a second provider walk.
    bound_names = (
        _PREPARING_ENV,
        _REFERENCE_MANIFEST_PATH_ENV,
        _REFERENCE_MANIFEST_ID_ENV,
    )
    prior = {name: os.environ.get(name) for name in bound_names}
    os.environ[_PREPARING_ENV] = "true"
    os.environ[_REFERENCE_MANIFEST_PATH_ENV] = manifest_path
    os.environ[_REFERENCE_MANIFEST_ID_ENV] = manifest_id
    try:
        snapshot = None
        try:
            snapshot = ensure_point_in_time_snapshot(values=values, allow_refresh=False)
        except ContinuousEvidencePlaneError:
            pass

        if snapshot is None or snapshot.reference_manifest_id != manifest_id:
            refresh_continuous_evidence_plane(
                values=values,
                reference_preparer=lambda _resolved: manifest,
            )
            snapshot = ensure_point_in_time_snapshot(values=values, allow_refresh=False)

        if snapshot.reference_manifest_id != manifest_id:
            raise ContinuousEvidencePlaneError(
                "point-in-time snapshot is not bound to the qualified reference manifest"
            )
    finally:
        _restore_environment(prior)
    return manifest


_install_recovery_progress_contract()
_core.prepare_reference_readiness = _prepare_with_rate_budget
_core._prime_forced_replacement = _prime_forced_replacement


if __name__ == "__main__":
    if "--force" in sys.argv[1:]:
        _prime_forced_replacement(os.environ)
    raise SystemExit(_core.main())

# Preserve the historical import surface. Test and library imports of
# run_bounded_manual_cio_diagnostic receive the unchanged core module after the runtime
# provider injection above, so module-global monkeypatches continue to affect the core.
sys.modules[__name__] = _core
