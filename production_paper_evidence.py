"""Governed facade preserving derivative-risk lineage for implementation wrappers.

The underlying evidence implementation remains unchanged. This facade only restores
instrument truth when a listed implementation wrapper obtains its economic exposure
through managed futures, option strategies, or volatility derivatives.
"""

from __future__ import annotations

from dataclasses import replace

import production_paper_evidence_impl as _implementation

_DERIVATIVE_WRAPPER_EXPOSURES = frozenset(
    {"managed_futures", "option_strategies", "volatility"}
)
_ORIGINAL_CANDIDATE_AND_EVIDENCE = _implementation._candidate_and_evidence


def _candidate_and_evidence(instrument, *args, **kwargs):
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


# Functions defined in the implementation module resolve globals from that module.
# Rebinding this one governed boundary ensures build_paper_evidence and direct callers
# share the same corrected candidate contract.
_implementation._candidate_and_evidence = _candidate_and_evidence

for _name, _value in vars(_implementation).items():
    if _name.startswith("__") or _name == "_candidate_and_evidence":
        continue
    globals()[_name] = _value

globals()["_candidate_and_evidence"] = _candidate_and_evidence
__all__ = tuple(getattr(_implementation, "__all__", ()))
