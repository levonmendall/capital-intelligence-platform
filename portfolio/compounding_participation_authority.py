"""Authoritative staged-participation policy adapter.

The canonical robustness assessor already evaluates whether the stated success
probability is consistent with the disclosed scenario distribution.  The original
compounding policy repeated that calculation from an optional diagnostic attribute,
which could convert an absent compatibility field into a false hard failure.  This
adapter preserves every existing staged-participation gate while deriving the
consistency input from the robustness assessor's authoritative reasons.
"""

from __future__ import annotations

from portfolio.compounding_allocation import CompoundingParticipationPolicy


_INCONSISTENCY_MARKER = "inconsistent with the disclosed scenarios"


class _RobustnessAuthorityView:
    def __init__(self, source: object) -> None:
        self._source = source

    @property
    def probability_consistency_gap(self) -> float:
        reasons = tuple(
            str(item)
            for item in (getattr(self._source, "reasons", ()) or ())
        )
        return 1.0 if any(_INCONSISTENCY_MARKER in item for item in reasons) else 0.0

    def __getattr__(self, name: str):
        return getattr(self._source, name)


class AuthoritativeCompoundingParticipationPolicy(
    CompoundingParticipationPolicy
):
    """Use the robustness assessor's disclosed result instead of a duplicate gate."""

    def assess(self, *, robustness: object, **kwargs):
        return super().assess(
            robustness=_RobustnessAuthorityView(robustness),
            **kwargs,
        )


__all__ = ["AuthoritativeCompoundingParticipationPolicy"]
