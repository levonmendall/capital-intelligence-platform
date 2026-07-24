"""Governed bridge from regime evidence to committee decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import isfinite

from committee.decision_discipline import (
    DissentDisposition,
    NoActionDecision,
    NoActionReason,
    StructuredDissent,
)
from committee.workflow import InstitutionalDecisionWorkflow
from economic_regime import Regime
from intelligence.investment_committee_consensus import (
    InvestmentCommitteeConsensus,
)
from intelligence.investment_committee_result import (
    InvestmentCommitteeResult,
)
from intelligence.recommendation import (
    ExpectedReturn,
    ExpectedRisk,
    InvestmentRecommendation,
    RecommendationAction,
    RecommendationLevel,
    RecommendationMagnitude,
    RecommendationStatus,
)
from intelligence.regime_pipeline import InstitutionalRegimeRun


class RegimeGovernanceOutcome(str, Enum):
    """Final governed disposition of a regime recommendation."""

    APPROVE = "approve"
    MODIFY = "modify"
    REJECT = "reject"
    ESCALATE = "escalate"
    NO_ACTION = "no_action"


@dataclass(frozen=True, slots=True)
class RegimeGovernancePolicy:
    """Explicit gates applied before and after committee evaluation."""

    version: str = "regime-governance.v1"
    minimum_data_coverage: float = 0.8
    minimum_quality_score: float = 0.75
    minimum_evidence_confidence: float = 0.55
    material_dissent_threshold: float = 0.5
    review_interval_days: int = 14

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version must be a non-empty string")
        object.__setattr__(self, "version", self.version.strip())
        for field_name in (
            "minimum_data_coverage",
            "minimum_quality_score",
            "minimum_evidence_confidence",
            "material_dissent_threshold",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
                raise ValueError(
                    f"{field_name} must be between 0.0 and 1.0"
                )
            object.__setattr__(self, field_name, normalized)
        if (
            isinstance(self.review_interval_days, bool)
            or not isinstance(self.review_interval_days, int)
        ):
            raise TypeError("review_interval_days must be an int")
        if self.review_interval_days < 1:
            raise ValueError("review_interval_days must be positive")


@dataclass(frozen=True, slots=True)
class RegimeCommitteeDecision:
    """Committee result plus the regime evidence and policy that governed it."""

    decision_identifier: str
    regime_run_identifier: str
    decided_at: datetime
    policy_version: str
    outcome: RegimeGovernanceOutcome
    recommendation: InvestmentRecommendation
    rationale: str
    committee_result: InvestmentCommitteeResult | None = None
    no_action: NoActionDecision | None = None
    dissents: tuple[StructuredDissent, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "decision_identifier",
            "regime_run_identifier",
            "policy_version",
            "rationale",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if not isinstance(self.decided_at, datetime):
            raise TypeError("decided_at must be a datetime")
        if (
            self.decided_at.tzinfo is None
            or self.decided_at.utcoffset() is None
        ):
            raise ValueError("decided_at must be timezone-aware")
        if not isinstance(self.outcome, RegimeGovernanceOutcome):
            raise TypeError("outcome must be a RegimeGovernanceOutcome")
        if not isinstance(self.recommendation, InvestmentRecommendation):
            raise TypeError(
                "recommendation must be an InvestmentRecommendation"
            )
        if self.committee_result is not None:
            if not isinstance(
                self.committee_result,
                InvestmentCommitteeResult,
            ):
                raise TypeError(
                    "committee_result must be an "
                    "InvestmentCommitteeResult"
                )
            if (
                self.committee_result.decision.recommendation
                != self.recommendation
            ):
                raise ValueError(
                    "committee_result must reference the recommendation"
                )
        elif self.outcome is not RegimeGovernanceOutcome.NO_ACTION:
            raise ValueError(
                "non-no-action outcome requires committee_result"
            )
        if not isinstance(self.dissents, tuple) or not all(
            isinstance(item, StructuredDissent)
            for item in self.dissents
        ):
            raise TypeError(
                "dissents must contain StructuredDissent values"
            )
        if self.outcome is RegimeGovernanceOutcome.NO_ACTION:
            if self.no_action is None:
                raise ValueError("no_action outcome requires no_action")
            if (
                self.no_action.decision_identifier
                != self.decision_identifier
            ):
                raise ValueError(
                    "no_action must reference the decision identifier"
                )
            if (
                self.no_action.recommendation_identifier
                != self.recommendation.identifier
            ):
                raise ValueError(
                    "no_action must reference the recommendation"
                )
        elif self.no_action is not None:
            raise ValueError(
                "no_action is only valid for a no_action outcome"
            )


_REGIME_POSITIONING = {
    Regime.GOLDILOCKS: (
        "diversified_risk_assets",
        RecommendationAction.OVERWEIGHT,
        RecommendationMagnitude.MODERATE,
        ExpectedReturn.HIGH,
        ExpectedRisk.MODERATE,
    ),
    Regime.REFLATION: (
        "real_assets_and_cyclicals",
        RecommendationAction.OVERWEIGHT,
        RecommendationMagnitude.MODERATE,
        ExpectedReturn.HIGH,
        ExpectedRisk.HIGH,
    ),
    Regime.STAGFLATION: (
        "broad_risk_assets",
        RecommendationAction.REDUCE,
        RecommendationMagnitude.MODERATE,
        ExpectedReturn.LOW,
        ExpectedRisk.VERY_HIGH,
    ),
    Regime.DISINFLATIONARY_SLOWDOWN: (
        "portfolio_risk_budget",
        RecommendationAction.NEUTRAL,
        RecommendationMagnitude.SMALL,
        ExpectedReturn.MODERATE,
        ExpectedRisk.MODERATE,
    ),
    Regime.CONTRACTION: (
        "broad_risk_assets",
        RecommendationAction.REDUCE,
        RecommendationMagnitude.LARGE,
        ExpectedReturn.VERY_LOW,
        ExpectedRisk.VERY_HIGH,
    ),
    Regime.TRANSITION: (
        "portfolio_risk_budget",
        RecommendationAction.NEUTRAL,
        RecommendationMagnitude.SMALL,
        ExpectedReturn.MODERATE,
        ExpectedRisk.HIGH,
    ),
}


def build_regime_recommendation(
    run: InstitutionalRegimeRun,
) -> InvestmentRecommendation:
    """Translate a canonical regime run into committee-ready input."""

    if not isinstance(run, InstitutionalRegimeRun):
        raise TypeError("run must be an InstitutionalRegimeRun")
    assessment = run.assessment
    result = assessment.result
    target, action, magnitude, expected_return, expected_risk = (
        _REGIME_POSITIONING[result.regime]
    )
    timestamp = run.as_of.isoformat()
    evidence = tuple(
        signal.explanation
        for signal in result.signals
        if signal.score is not None
    ) or ("No scored regime signals are currently available.",)
    risks = result.risks or (
        "The classified regime can change as new evidence arrives.",
    )
    return InvestmentRecommendation(
        identifier=f"regime-recommendation:{timestamp}",
        title=f"{result.regime.value} macro positioning",
        level=RecommendationLevel.MACRO,
        target=target,
        action=action,
        magnitude=magnitude,
        status=(
            RecommendationStatus.WATCH
            if result.regime is Regime.TRANSITION
            else RecommendationStatus.ACTIVE
        ),
        confidence=assessment.confidence,
        source_thesis_identifier=f"regime-thesis:{timestamp}",
        rationale=result.conclusion,
        supporting_evidence=evidence,
        contradicting_evidence=tuple(result.risks),
        catalysts=(
            "New point-in-time macro releases confirm the regime.",
        ),
        risks=risks,
        invalidation_conditions=(
            "The deterministic classifier changes regime.",
            "Evidence quality or coverage falls below governance policy.",
        ),
        expected_return=expected_return,
        expected_risk=expected_risk,
        expected_duration_months=12,
    )


class RegimeGovernanceWorkflow:
    """Apply evidence gates, committee governance, dissent, and disposition."""

    def __init__(
        self,
        *,
        committee_workflow: InstitutionalDecisionWorkflow | None = None,
        policy: RegimeGovernancePolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.committee_workflow = (
            committee_workflow or InstitutionalDecisionWorkflow()
        )
        self.policy = policy or RegimeGovernancePolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def evaluate(
        self,
        run: InstitutionalRegimeRun,
        *,
        regime_run_identifier: str | None = None,
        dissents: tuple[StructuredDissent, ...] = (),
    ) -> RegimeCommitteeDecision:
        """Return one governed, non-executing regime decision."""

        if not isinstance(run, InstitutionalRegimeRun):
            raise TypeError("run must be an InstitutionalRegimeRun")
        if not isinstance(dissents, tuple) or not all(
            isinstance(item, StructuredDissent) for item in dissents
        ):
            raise TypeError(
                "dissents must contain StructuredDissent values"
            )
        decided_at = self._clock()
        if decided_at.tzinfo is None or decided_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        run_identifier = regime_run_identifier or (
            f"regime:{run.as_of.isoformat()}"
        )
        recommendation = build_regime_recommendation(run)
        decision_identifier = (
            f"regime-committee-decision:{run.as_of.isoformat()}"
        )

        gate = self._evidence_gate(run)
        if gate is not None:
            reason, rationale = gate
            no_action = NoActionDecision(
                decision_identifier=decision_identifier,
                reason=reason,
                rationale=rationale,
                decided_at=decided_at,
                review_at=(
                    decided_at
                    + timedelta(days=self.policy.review_interval_days)
                ),
                evidence_identifiers=(
                    f"regime-evidence:{run.as_of.isoformat()}",
                ),
                action_triggers=(
                    "Required evidence clears all governance thresholds.",
                    "A new canonical regime run is recorded.",
                ),
                recommendation_identifier=recommendation.identifier,
            )
            return RegimeCommitteeDecision(
                decision_identifier=decision_identifier,
                regime_run_identifier=run_identifier,
                decided_at=decided_at,
                policy_version=self.policy.version,
                outcome=RegimeGovernanceOutcome.NO_ACTION,
                recommendation=recommendation,
                rationale=rationale,
                no_action=no_action,
                dissents=dissents,
            )

        committee_result = self.committee_workflow.evaluate(
            recommendation
        )
        material_open_dissent = tuple(
            dissent
            for dissent in dissents
            if (
                dissent.disposition is DissentDisposition.OPEN
                and dissent.materiality
                >= self.policy.material_dissent_threshold
            )
        )
        if material_open_dissent:
            return RegimeCommitteeDecision(
                decision_identifier=decision_identifier,
                regime_run_identifier=run_identifier,
                decided_at=decided_at,
                policy_version=self.policy.version,
                outcome=RegimeGovernanceOutcome.ESCALATE,
                recommendation=recommendation,
                rationale=(
                    "Material unresolved dissent requires explicit "
                    "committee escalation before portfolio action."
                ),
                committee_result=committee_result,
                dissents=dissents,
            )

        outcome = self._map_consensus(
            committee_result.decision.consensus
        )
        no_action = None
        if outcome is RegimeGovernanceOutcome.NO_ACTION:
            no_action = NoActionDecision(
                decision_identifier=decision_identifier,
                reason=NoActionReason.NO_EDGE,
                rationale=(
                    "Committee consensus did not authorize a portfolio "
                    "change."
                ),
                decided_at=decided_at,
                review_at=(
                    decided_at
                    + timedelta(days=self.policy.review_interval_days)
                ),
                evidence_identifiers=(
                    f"regime-evidence:{run.as_of.isoformat()}",
                ),
                action_triggers=(
                    "Committee consensus changes after new evidence.",
                ),
                recommendation_identifier=recommendation.identifier,
            )
        return RegimeCommitteeDecision(
            decision_identifier=decision_identifier,
            regime_run_identifier=run_identifier,
            decided_at=decided_at,
            policy_version=self.policy.version,
            outcome=outcome,
            recommendation=recommendation,
            rationale=(
                "Committee consensus "
                f"{committee_result.decision.consensus.value} mapped to "
                f"governance outcome {outcome.value}."
            ),
            committee_result=committee_result,
            no_action=no_action,
            dissents=dissents,
        )

    def _evidence_gate(
        self,
        run: InstitutionalRegimeRun,
    ) -> tuple[NoActionReason, str] | None:
        evidence = run.assessment.evidence
        if evidence.data_coverage < self.policy.minimum_data_coverage:
            return (
                NoActionReason.INSUFFICIENT_EVIDENCE,
                "Regime evidence coverage is below governance policy.",
            )
        if evidence.quality_score < self.policy.minimum_quality_score:
            return (
                NoActionReason.DATA_QUALITY,
                "Regime evidence quality is below governance policy.",
            )
        if (
            run.assessment.confidence
            < self.policy.minimum_evidence_confidence
        ):
            return (
                NoActionReason.WAIT_FOR_TRIGGER,
                "Evidence-adjusted regime confidence is below policy.",
            )
        if run.assessment.result.regime is Regime.TRANSITION:
            return (
                NoActionReason.WAIT_FOR_TRIGGER,
                "A transition regime requires new confirming evidence.",
            )
        return None

    @staticmethod
    def _map_consensus(
        consensus: InvestmentCommitteeConsensus,
    ) -> RegimeGovernanceOutcome:
        if consensus in {
            InvestmentCommitteeConsensus.STRONG_APPROVAL,
            InvestmentCommitteeConsensus.APPROVAL,
        }:
            return RegimeGovernanceOutcome.APPROVE
        if (
            consensus
            is InvestmentCommitteeConsensus.APPROVAL_WITH_CONDITIONS
        ):
            return RegimeGovernanceOutcome.MODIFY
        if consensus is InvestmentCommitteeConsensus.REJECT:
            return RegimeGovernanceOutcome.REJECT
        if consensus is InvestmentCommitteeConsensus.DEFER:
            return RegimeGovernanceOutcome.ESCALATE
        return RegimeGovernanceOutcome.NO_ACTION


__all__ = [
    "RegimeCommitteeDecision",
    "RegimeGovernanceOutcome",
    "RegimeGovernancePolicy",
    "RegimeGovernanceWorkflow",
    "build_regime_recommendation",
]
