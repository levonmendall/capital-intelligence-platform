"""Non-executing joint portfolio preview contract for CIO sizing context.

The preview is produced by the existing construction engine before final CIO
synthesis. It can only reduce a positive CIO target to a smaller simultaneously
feasible positive target. It cannot create a candidate, authorize an action, force
an exit, or replace final portfolio construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _weight(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return round(normalized, 8)


def _mapping(
    values: object,
    *,
    field_name: str,
) -> tuple[tuple[str, float], ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        (
            _text(identifier, field_name=f"{field_name} identifier"),
            _weight(weight, field_name=f"{field_name} weight"),
        )
        for identifier, weight in values
    )
    identifiers = tuple(identifier for identifier, _ in normalized)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{field_name} candidate identifiers must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class JointPortfolioPreview:
    """One simultaneous construction preview supplied to the CIO as sizing context."""

    identifier: str
    status: str
    policy_version: str
    requested_targets: tuple[tuple[str, float], ...]
    joint_targets: tuple[tuple[str, float], ...]
    target_cash_weight: float
    expected_return_improvement: float
    blocks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "status", "policy_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "requested_targets",
            _mapping(self.requested_targets, field_name="requested_targets"),
        )
        object.__setattr__(
            self,
            "joint_targets",
            _mapping(self.joint_targets, field_name="joint_targets"),
        )
        if {item for item, _ in self.requested_targets} != {
            item for item, _ in self.joint_targets
        }:
            raise ValueError(
                "requested_targets and joint_targets must cover the same candidates"
            )
        object.__setattr__(
            self,
            "target_cash_weight",
            _weight(self.target_cash_weight, field_name="target_cash_weight"),
        )
        if isinstance(self.expected_return_improvement, bool) or not isinstance(
            self.expected_return_improvement,
            (int, float),
        ):
            raise TypeError("expected_return_improvement must be numeric")
        improvement = float(self.expected_return_improvement)
        if not isfinite(improvement):
            raise ValueError("expected_return_improvement must be finite")
        object.__setattr__(
            self,
            "expected_return_improvement",
            round(improvement, 8),
        )
        if not isinstance(self.blocks, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.blocks
        ):
            raise TypeError("blocks must contain non-empty strings")
        object.__setattr__(
            self,
            "blocks",
            tuple(dict.fromkeys(item.strip() for item in self.blocks)),
        )

    def requested_for(self, candidate_identifier: str) -> float | None:
        resolved = _text(candidate_identifier, field_name="candidate_identifier")
        return next(
            (weight for identifier, weight in self.requested_targets if identifier == resolved),
            None,
        )

    def target_for(self, candidate_identifier: str) -> float | None:
        resolved = _text(candidate_identifier, field_name="candidate_identifier")
        return next(
            (weight for identifier, weight in self.joint_targets if identifier == resolved),
            None,
        )

    def positive_cap_for(
        self,
        candidate_identifier: str,
        *,
        current_weight: float,
    ) -> float | None:
        """Return only a smaller still-positive simultaneous target.

        A zero joint target can reflect competition among several otherwise valid
        candidates. It is therefore evidence for final construction, not a hidden CIO
        veto. Only a target that remains above the current weight may cap a positive
        action before final construction.
        """

        current = _weight(current_weight, field_name="current_weight")
        requested = self.requested_for(candidate_identifier)
        target = self.target_for(candidate_identifier)
        if requested is None or target is None:
            return None
        if target <= current + 0.00000001:
            return None
        if target >= requested - 0.00000001:
            return None
        return target

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "joint-portfolio-preview.v1",
            "identifier": self.identifier,
            "status": self.status,
            "policy_version": self.policy_version,
            "requested_targets": dict(self.requested_targets),
            "joint_targets": dict(self.joint_targets),
            "target_cash_weight": self.target_cash_weight,
            "expected_return_improvement": self.expected_return_improvement,
            "blocks": list(self.blocks),
            "investment_authority": False,
            "execution_authority": False,
            "can_only_cap_positive_target": True,
            "zero_target_is_not_a_cio_veto": True,
        }


__all__ = ["JointPortfolioPreview"]
