"""Runtime entrypoint for the bounded CIO diagnostic reference layer.

The watchdog core stays unchanged. This entrypoint injects generalized persistent
reference readiness plus the governed, rate-budgeted Massive futures provider before the
core starts reference preparation. Imported callers receive the core module so existing
tests and monkeypatches keep their behavior.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

import run_bounded_manual_cio_diagnostic_core as _core
from operations.generalized_reference_readiness import (
    prepare_reference_readiness as _prepare_reference,
)
from providers.massive_futures_reference_bounded import MassiveFuturesReferenceProvider


def _prepare_with_rate_budget(
    values: Mapping[str, str],
    **kwargs: object,
):
    kwargs.setdefault(
        "massive_futures_provider",
        MassiveFuturesReferenceProvider(),
    )
    return _prepare_reference(values, **kwargs)


_core.prepare_reference_readiness = _prepare_with_rate_budget


if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve the historical import surface. Test and library imports of
# run_bounded_manual_cio_diagnostic receive the unchanged core module after the runtime
# provider injection above, so module-global monkeypatches continue to affect the core.
sys.modules[__name__] = _core
