"""Govern the manual CIO diagnostic's production dependency boundaries.

The implementation remains in ``_manual_cio_diagnostic_core`` so its mature lazy-import,
resource, CIO, construction, and paper-only behavior stays unchanged. This adapter owns the
production dependencies that must remain governed and memory-bounded: canonical portfolio
initialization, historical replay consumption during worker initialization, and the exact-
release all-market certification handoff after the worker reports analytical completion.
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


class _ExactReleaseCertificationGuard:
    """Require durable all-market construction proof before terminal handoff.

    The scheduler's generic ``completed`` result means its triggered analytical job ended;
    it is not, by itself, proof that the comprehensive exact-release certification state
    machine reached every required all-market stage.  The comprehensive release diagnostic
    already owns a durable, exact-cutoff state machine.  When that state machine is enabled,
    this lightweight proxy requires it to have reached construction (or a later terminal
    state) before the manual diagnostic may cross into paper implementation.
    """

    def __init__(self, worker: object) -> None:
        self._worker = worker

    def __getattr__(self, name: str) -> object:
        return getattr(self._worker, name)

    def run_triggered(self, *args: object, **kwargs: object) -> object:
        result = self._worker.run_triggered(*args, **kwargs)
        if str(getattr(result, "status", "")).strip().lower() != "completed":
            return result

        from operations.certification_runtime_state import (
            certification_runtime_enabled,
            resolve_certification_for_cutoff,
        )
        from operations.certification_state_machine import CertificationState

        if not certification_runtime_enabled():
            return result

        decision_as_of = kwargs.get("decision_as_of")
        if decision_as_of is None:
            raise RuntimeError(
                "exact-release certification handoff lacks the authoritative decision cutoff"
            )
        binding = resolve_certification_for_cutoff(decision_as_of)
        acceptable_states = {
            CertificationState.CONSTRUCTION_COMPLETE,
            CertificationState.PAPER_IMPLEMENTED,
            CertificationState.NO_ACTION,
            CertificationState.CERTIFIED,
        }
        if binding.current_state not in acceptable_states:
            raise RuntimeError(
                "all-market certification prerequisite is incomplete at worker handoff: "
                f"current={binding.current_state.value}, "
                "required=construction_complete"
            )
        return result


def _load_worker_dependency() -> None:
    """Install bounded replay access and the exact-release certification handoff guard."""

    if _core.build_worker is None:
        from operations.bounded_governed_historical_learning import (
            install_bounded_governed_historical_learning,
        )

        install_bounded_governed_historical_learning()
        from run_scheduler import build_worker as implementation

        def guarded_build_worker(settings: object) -> _ExactReleaseCertificationGuard:
            return _ExactReleaseCertificationGuard(implementation(settings))

        _core.build_worker = guarded_build_worker


# Replace core lazy loaders before execution. The adapter itself remains lightweight; neither
# portfolio, operations, nor scheduler/application graphs are imported at process startup.
_core._load_canonical_dependency = _load_canonical_dependency
_core._load_worker_dependency = _load_worker_dependency

if __name__ == "__main__":
    raise SystemExit(_core.main())

# Preserve the established import/monkeypatch surface used by diagnostic tests and callers.
sys.modules[__name__] = _core
