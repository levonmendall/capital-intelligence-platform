"""Multi-asset performance evidence for the existing living-thesis authority.

This adapter does not create a second thesis engine.  It validates one governed
multi-asset return observation against an existing ``LivingThesis``, preserves the
asset/currency/cost decomposition, and creates the standard ``ThesisEvidenceUpdate``
consumed by ``ThesisMonitor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from evaluation.multi_asset import MultiAssetReturnObservation
from thesis.models import LivingThesis, ThesisEvidenceUpdate


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 12)


@dataclass(frozen=True, slots=True)
class MultiAssetThesisAssessment:
    """Transparent attribution attached to one standard thesis update."""

    identifier: str
    thesis_identifier: str
    observation_identifier: str
    evaluated_at: datetime
    local_asset_return: float
    currency_return: float
    interaction_return: float
    implementation_cost_return: float
    net_base_return: float
    currency_material: bool
    triggered_invalidation_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "multi-asset-thesis-assessment.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "thesis_identifier",
            "observation_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.evaluated_at, datetime):
            raise TypeError("evaluated_at must be a datetime")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        for field_name in (
            "local_asset_return",
            "currency_return",
            "interaction_return",
            "implementation_cost_return",
            "net_base_return",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name),
            )
        if self.implementation_cost_return < 0.0:
            raise ValueError("implementation_cost_return cannot be negative")
        if not isinstance(self.currency_material, bool):
            raise TypeError("currency_material must be a bool")
        object.__setattr__(
            self,
            "triggered_invalidation_conditions",
            _texts(
                self.triggered_invalidation_conditions,
                field_name="triggered_invalidation_conditions",
            ),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers"),
        )
        if not self.evidence_identifiers:
            raise ValueError("multi-asset thesis assessment requires evidence")
        reconciled = (
            self.local_asset_return
            + self.currency_return
            + self.interaction_return
            - self.implementation_cost_return
        )
        if abs(reconciled - self.net_base_return) > 0.0000001:
            raise ValueError("thesis performance attribution must reconcile")

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "thesis_identifier": self.thesis_identifier,
            "observation_identifier": self.observation_identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "local_asset_return": self.local_asset_return,
            "currency_return": self.currency_return,
            "interaction_return": self.interaction_return,
            "implementation_cost_return": self.implementation_cost_return,
            "net_base_return": self.net_base_return,
            "currency_material": self.currency_material,
            "triggered_invalidation_conditions": list(
                self.triggered_invalidation_conditions
            ),
            "evidence_identifiers": list(self.evidence_identifiers),
            "schema_version": self.schema_version,
        }


class MultiAssetThesisEvidenceAdapter:
    """Create a standard thesis update from decomposed multi-asset evidence."""

    def __init__(self, *, currency_materiality_threshold: float = 0.02) -> None:
        self.currency_materiality_threshold = _number(
            currency_materiality_threshold,
            field_name="currency_materiality_threshold",
            minimum=0.0,
        )

    def build(
        self,
        thesis: LivingThesis,
        observation: MultiAssetReturnObservation,
        *,
        expected_return: float,
        expected_downside: float,
        confidence: float,
        strengthened_indicators: tuple[str, ...],
        weakened_indicators: tuple[str, ...],
        triggered_invalidation_conditions: tuple[str, ...],
        data_current: bool,
        best_replacement_expected_return: float,
        next_review_at: datetime,
        additional_evidence_identifiers: tuple[str, ...] = (),
    ) -> tuple[MultiAssetThesisAssessment, ThesisEvidenceUpdate]:
        if not isinstance(thesis, LivingThesis):
            raise TypeError("thesis must be LivingThesis")
        if not isinstance(observation, MultiAssetReturnObservation):
            raise TypeError("observation must be MultiAssetReturnObservation")
        if observation.thesis_identifier != thesis.identifier:
            raise ValueError("multi-asset observation does not match thesis")
        if observation.decision_identifier != thesis.decision_identifier:
            raise ValueError("multi-asset observation does not match thesis decision")
        if observation.symbol != thesis.asset.upper():
            raise ValueError("multi-asset observation does not match thesis asset")
        evidence_ids = tuple(
            dict.fromkeys(
                thesis.evidence_identifiers
                + observation.evidence_identifiers
                + observation.source_identifiers
                + observation.quote_source_identifiers
                + observation.fx_source_identifiers
                + additional_evidence_identifiers
            )
        )
        invalidations = _texts(
            triggered_invalidation_conditions,
            field_name="triggered_invalidation_conditions",
        )
        assessment = MultiAssetThesisAssessment(
            identifier=f"multi-asset-thesis:{thesis.identifier}:{observation.observed_at.isoformat()}",
            thesis_identifier=thesis.identifier,
            observation_identifier=observation.identifier,
            evaluated_at=observation.observed_at,
            local_asset_return=observation.implementation_local_return,
            currency_return=observation.implementation_currency_return,
            interaction_return=observation.implementation_interaction_return,
            implementation_cost_return=observation.implementation_cost_return,
            net_base_return=observation.implementation_net_base_return,
            currency_material=(
                abs(observation.implementation_currency_return)
                >= self.currency_materiality_threshold
            ),
            triggered_invalidation_conditions=invalidations,
            evidence_identifiers=evidence_ids,
        )
        update = ThesisEvidenceUpdate(
            thesis_identifier=thesis.identifier,
            as_of=observation.observed_at,
            expected_return=expected_return,
            expected_downside=expected_downside,
            confidence=confidence,
            evidence_identifiers=evidence_ids,
            strengthened_indicators=_texts(
                strengthened_indicators,
                field_name="strengthened_indicators",
            ),
            weakened_indicators=_texts(
                weakened_indicators,
                field_name="weakened_indicators",
            ),
            triggered_invalidation_conditions=invalidations,
            data_current=data_current,
            performance_since_approval=observation.implementation_net_base_return,
            best_replacement_expected_return=best_replacement_expected_return,
            next_review_at=next_review_at,
        )
        return assessment, update


__all__ = [
    "MultiAssetThesisAssessment",
    "MultiAssetThesisEvidenceAdapter",
]
