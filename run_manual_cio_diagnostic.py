"""Govern the manual CIO diagnostic's canonical-portfolio initialization authority.

The implementation remains in ``_manual_cio_diagnostic_core`` so its mature lazy-import,
resource, CIO, construction, and paper-only behavior stays byte-for-byte unchanged. This
adapter owns the production dependencies that must remain governed and memory-bounded:
canonical portfolio initialization and historical replay consumption.
"""

from __future__ import annotations

import sys

from operations.bounded_historical_learning import install_bounded_historical_learning

# The bounded diagnostic runs one canonical cycle in an isolated child process. Install the
# streaming historical-replay reader before the core prepares specialist/CIO dependencies so
# a large replay manifest can never be expanded repeatedly into the child heap.
install_bounded_historical_learning()

import _manual_cio_diagnostic_core as _core


def _load_canonical_dependency() -> None:
    """Lazily bind only the governed ABSENT / VALID / INVALID initializer."""

    if _core.ensure_canonical_portfolio_store is None:
        from portfolio.initialization import (
            ensure_canonical_portfolio_store as governed_initializer,
        )

        _core.ensure_canonical_portfolio_store = governed_initializer


# Replace the core loader before execution so the canonical phase stays memory-bounded while
# controlled dependency resets can never fall back to portfolio.state's legacy initializer.
_core._load_canonical_dependency = _load_canonical_dependency

if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve the established import/monkeypatch surface used by diagnostic tests and callers.
sys.modules[__name__] = _core
