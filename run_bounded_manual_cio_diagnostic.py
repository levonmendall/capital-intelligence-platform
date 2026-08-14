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
from operations.cme_futures_reference_runtime import (
    install_cme_futures_reference_lineage,
)
from operations.continuous_evidence_plane import (
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
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


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


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


def _prepare_with_rate_budget(
    values: Mapping[str, str],
    **kwargs: object,
):
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

    # Comprehensive discovery is itself used to populate the evidence plane. Mark this
    # pre-clock preparation so the discovery facade does not recursively request a
    # snapshot while the snapshot is being built.
    prior = os.environ.get(_PREPARING_ENV)
    os.environ[_PREPARING_ENV] = "true"
    try:
        ensure_point_in_time_snapshot(values=values, allow_refresh=True)
    finally:
        if prior is None:
            os.environ.pop(_PREPARING_ENV, None)
        else:
            os.environ[_PREPARING_ENV] = prior
    return manifest


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
