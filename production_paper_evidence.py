"""Governed facade preserving paper-evidence compatibility and risk lineage.

The complete implementation remains in ``production_paper_evidence_impl``. This
facade preserves the historical module-level monkeypatch boundary used by tests and
operations while restoring derivative-risk truth for listed implementation wrappers.
"""

from __future__ import annotations

from dataclasses import replace

import production_paper_evidence_impl as _implementation
from providers.sec_edgar_resilient import ResilientSECEdgarProvider

_DERIVATIVE_WRAPPER_EXPOSURES = frozenset(
    {"managed_futures", "option_strategies", "volatility"}
)
_ORIGINAL_DEFAULT_PROBE = _implementation._default_probe
_ORIGINAL_COLLECT_PAPER_EVIDENCE = _implementation.collect_paper_evidence
_ORIGINAL_BUILD_PAPER_EVIDENCE = _implementation.build_paper_evidence
_ORIGINAL_CANDIDATE_AND_EVIDENCE = _implementation._candidate_and_evidence
_IMPLEMENTATION_NAMES = tuple(vars(_implementation))
_WRAPPED_NAMES = frozenset(
    {
        "_default_probe",
        "collect_paper_evidence",
        "build_paper_evidence",
        "_candidate_and_evidence",
        "SECEdgarProvider",
    }
)


for _name, _value in vars(_implementation).items():
    if _name.startswith("__") or _name in _WRAPPED_NAMES:
        continue
    globals()[_name] = _value


SECEdgarProvider = ResilientSECEdgarProvider


def _synchronize_runtime_bindings() -> None:
    """Propagate facade monkeypatches into implementation function globals."""

    for name in _IMPLEMENTATION_NAMES:
        if name.startswith("__") or name in _WRAPPED_NAMES:
            continue
        if name in globals():
            _implementation.__dict__[name] = globals()[name]
    _implementation._default_probe = _default_probe
    _implementation._candidate_and_evidence = _candidate_and_evidence
    _implementation.SECEdgarProvider = SECEdgarProvider


def _default_probe(*args, **kwargs):
    _synchronize_runtime_bindings()
    return _ORIGINAL_DEFAULT_PROBE(*args, **kwargs)


def collect_paper_evidence(*args, **kwargs):
    _synchronize_runtime_bindings()
    return _ORIGINAL_COLLECT_PAPER_EVIDENCE(*args, **kwargs)


def _candidate_and_evidence(instrument, *args, **kwargs):
    _synchronize_runtime_bindings()
    candidate, evidence = _ORIGINAL_CANDIDATE_AND_EVIDENCE(
        instrument,
        *args,
        **kwargs,
    )
    uses_derivatives = (
        instrument.uses_derivatives
        or instrument.economic_exposure in _DERIVATIVE_WRAPPER_EXPOSURES
    )
    if uses_derivatives and not candidate.instrument.uses_derivatives:
        candidate = replace(
            candidate,
            instrument=replace(candidate.instrument, uses_derivatives=True),
        )
    return candidate, evidence


def build_paper_evidence(*args, **kwargs):
    _synchronize_runtime_bindings()
    return _ORIGINAL_BUILD_PAPER_EVIDENCE(*args, **kwargs)


_implementation._default_probe = _default_probe
_implementation._candidate_and_evidence = _candidate_and_evidence
_implementation.SECEdgarProvider = SECEdgarProvider
__all__ = tuple(getattr(_implementation, "__all__", ()))
