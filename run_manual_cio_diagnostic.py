"""Govern the manual CIO diagnostic's canonical-portfolio initialization authority.

The implementation remains in ``run_manual_cio_diagnostic_core`` so its mature lazy-import,
resource, CIO, construction, and paper-only behavior stays byte-for-byte unchanged.  This
adapter owns the one production dependency that must never fall back to the legacy
reset/archive-capable compatibility initializer: canonical portfolio initialization.
"""

from __future__ import annotations

import sys

import run_manual_cio_diagnostic_core as _core
from portfolio.initialization import (
    ensure_canonical_portfolio_store as _governed_canonical_initializer,
)


def _load_canonical_dependency() -> None:
    """Bind only the governed ABSENT / VALID / INVALID initializer."""

    if _core.ensure_canonical_portfolio_store is None:
        _core.ensure_canonical_portfolio_store = _governed_canonical_initializer


# Bind eagerly for ordinary execution and replace the core loader so tests or controlled
# dependency resets cannot reintroduce portfolio.state's legacy reset-capable initializer.
_core.ensure_canonical_portfolio_store = _governed_canonical_initializer
_core._load_canonical_dependency = _load_canonical_dependency

if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve the established import/monkeypatch surface used by diagnostic tests and callers.
sys.modules[__name__] = _core
