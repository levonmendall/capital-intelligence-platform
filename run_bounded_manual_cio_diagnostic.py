"""Runtime entrypoint for bounded CIO reference and evidence readiness.

The watchdog core stays unchanged. This entrypoint injects generalized persistent
reference readiness plus the governed, rate-budgeted Massive futures provider.  In the
production service it also qualifies the continuous evidence plane before the bounded
CIO child starts, so a cold historical bootstrap cannot consume the CIO's 30-minute
analysis deadline. Imported callers receive the core module so existing tests and
monkeypatches keep their behavior.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

import run_bounded_manual_cio_diagnostic_core as _core
from operations.continuous_evidence_plane import (
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
from operations.generalized_reference_readiness import (
    prepare_reference_readiness as _prepare_reference,
)
from providers.massive_futures_reference_bounded import MassiveFuturesReferenceProvider

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"


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
    kwargs.setdefault(
        "massive_futures_provider",
        MassiveFuturesReferenceProvider(),
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


if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve the historical import surface. Test and library imports of
# run_bounded_manual_cio_diagnostic receive the unchanged core module after the runtime
# provider injection above, so module-global monkeypatches continue to affect the core.
sys.modules[__name__] = _core
