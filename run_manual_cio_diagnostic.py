"""Govern the manual CIO diagnostic's production dependency boundaries.

The implementation remains in ``_manual_cio_diagnostic_core`` so its mature lazy-import,
resource, CIO, construction, and paper-only behavior stays unchanged. This adapter owns the
production dependencies that must remain governed and memory-bounded: canonical portfolio
initialization and historical replay consumption during worker initialization.
"""

from __future__ import annotations

import sys

import _manual_cio_diagnostic_core as _core


def _load_canonical_dependency() -> None:
    """Lazily bind only the governed ABSENT / VALID / INVALID initializer."""

    if _core.ensure_canonical_portfolio_store is None:
        from portfolio.initialization import (
            ensure_canonical_portfolio_store as governed_initializer,
        )

        _core.ensure_canonical_portfolio_store = governed_initializer


def _load_worker_dependency() -> None:
    """Install bounded replay access only when the specialist/CIO worker is needed."""

    if _core.build_worker is None:
        from operations.bounded_governed_historical_learning import (
            install_bounded_governed_historical_learning,
        )

        install_bounded_governed_historical_learning()
        from run_scheduler import build_worker as implementation

        _core.build_worker = implementation


# Replace core lazy loaders before execution. The adapter itself remains lightweight; neither
# portfolio, operations, nor scheduler/application graphs are imported at process startup.
_core._load_canonical_dependency = _load_canonical_dependency
_core._load_worker_dependency = _load_worker_dependency

if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve the established import/monkeypatch surface used by diagnostic tests and callers.
sys.modules[__name__] = _core
