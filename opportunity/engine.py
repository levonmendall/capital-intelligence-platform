"""Formal pre-committee opportunity qualification and ranking engine."""

from __future__ import annotations

from dataclasses import dataclass

from cio import CandidateDecisionRecord, RecommendationUniversePolicy
from cio.policy_matrix import DecisionPolicyMatrix
from cio.robustness import (
    RobustCandidateAssessment,
    RobustCandidateAssessor,
    RobustDecisionPolicy,
)
from opportunity.models import (
    AnalysisLane,
    AlternativeKind,
    CandidateQualification,
    OpportunityQueue,
    OpportunitySetContext,
    OpportunityRankingInput,
    QualificationOutcome,
    RankedOpportunity,
    ScoreComponent,
)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 8)


@dataclass(frozen=True, slots=True)
class OpportunityQualificationPolicy:
    """Versioned committee-attention and opportunity-ranking rules."""

    version: str = "opportunity-qualification.v5"
    minimum_net_expected_return: float = 0.05
    minimum_probability_of_success: float = 0.55
    minimum_evidence_score: float = 0.70
    minimum_evidence_dimension: float = 0.50
    minimum_liquidity_score: float = 0.70
    minimum_opportunity_edge: float = 0.01
    maximum_expected_downside: float = -0.35
    maximum_implementation_cost_return: float = 0.02
    opportunity_cost_tolerance: float = 0.005

    expected_return_weight: float = 0.21
    probability_weight: float = 0.10
    downside_weight: float = 0.10
    evidence_weight: float = 0.14
    freshness_weight: float = 0.05
    independence_weight: float = 0.05
    liquidity_weight: float = 0.07
    opportunity_edge_weight: float = 0.10
    portfolio_contribution_weight: float = 0.07
    thesis_clarity_weight: float = 0.04
    invalidation_clarity_weight: float = 0.03
    forecast_durability_weight: float = 0.02
    cost_efficiency_weight: float = 0.02

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "minimum_probability_of_success",
            "minimum_evidence_score",
            "minimum_evidence_dimension",
            "minimum_liquidity_score",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        if self.maximum_expected_downside > 0.0:
            raise ValueError("maximum_expected_downside must be zero or negative")
        if self.maximum_implementation_cost_return <= 0.0:
            raise ValueError(
                "maximum_implementation_cost_return must be positive"
            )
        if self.opportunity_cost_tolerance < 0.0:
            raise ValueError("opportunity_cost_tolerance cannot be negative")
        weights = self.weights
        if abs(sum(weights.values()) - 1.0) > 0.000001:
            raise ValueError("opportunity ranking weights must sum to 1.0")
        if any(value < 0.0 for value in weights.values()):
            raise ValueError("opportunity ranking weights cannot be negative")

    @property
    def weights(self) -> dict[str, float]:
        return {
            "net_expected_return": self.expected_return_weight,
            "probability_of_success": self.probability_weight,
            "downside_protection": self.downside_weight,
            "evidence_quality": self.evidence_weight,
            "evidence_freshness": self.freshness_weight,
            "evidence_independence": self.independence_weight,
            "liquidity": self.liquidity_weight,
            "opportunity_edge": self.opportunity_edge_weight,
            "portfolio_contribution": self.portfolio_contribution_weight,
            "thesis_clarity": self.thesis_clarity_weight,
            "invalidation_clarity": self.invalidation_clarity_weight,
            "forecast_durability": self.forecast_durability_weight,
            "cost_efficiency": self.cost_efficiency_weight,
        }


class OpportunityEngine:
    """Reduce the investable universe to a robust ranked specialist-review queue."""

    def __init__(
        self,
        *,
        universe_policy: RecommendationUniversePolicy | None = None,
        qualification_policy: OpportunityQualificationPolicy | None = None,
        robustness_policy: RobustDecisionPolicy | None = None,
        policy_matrix: DecisionPolicyMatrix | None = None,
    ) -> None:
        self.universe_policy = universe_policy or RecommendationUniversePolicy()
        self.policy = qualification_policy or OpportunityQualificationPolicy()
        self._default_policy = OpportunityQualificationPolicy()
        self.robust_assessor = RobustCandidateAssessor(robustness_policy)
        self.policy_matrix = policy_matrix or DecisionPolicyMatrix()

    def build_queue(
        self,
        candidates: tuple[CandidateDecisionRecord, ...],
        context: OpportunitySetContext,
    ) -> OpportunityQueue:
        if not isinstance(candidates, tuple) or not all(
            isinstance(item, CandidateDecisionRecord) for item in candidates
        ):
            raise TypeError(
                "candidates must be a tuple of CandidateDecisionRecord values"
            )
        if not isinstance(context, OpportunitySetContext):
            raise TypeError("context must be an OpportunitySetContext")
        identifiers = tuple(item.identifier for item in candidates)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate identifiers must be unique")
        instrument_ids = tuple(item.instrument.instrument_id for item in candidates)
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError(
                "one opportunity set cannot contain duplicate instrument candidates"
            )
        if any(item.as_of != context.as_of for item in candidates):
            raise ValueError(
                "all candidates must share the opportunity-set decision timestamp"
            )

        qualified: list[
            tuple[
                CandidateDecisionRecord,
                CandidateQualification,
                RobustCandidateAssessment,
                tuple[ScoreComponent, ...],
                float,
            ]
        ] = []
        rejected: list[CandidateQualification] = []
        for candidate in candidates:
            qualification, robustness = self._qualify_with_robustness(
                candidate,
                context,
            )
            if not qualification.qualified:
                rejected.append(qualification)
                continue
            components = self._components(candidate, qualification, robustness, context)
            score = round(sum(item.contribution for item in components), 8)
            qualified.append(
                (candidate, qualification, robustness, components, score)
            )

        qualified.sort(
            key=lambda item: (
                1 if item[1].analysis_lane is AnalysisLane.HOLDING_REVIEW else 0,
                item[4],
                item[2].stressed_edge,
                item[2].robust_edge,
                item[2].annualized_geometric_return,
                item[0].evidence_quality.score,
                item[0].instrument.symbol,
            ),
            reverse=True,
        )
        ranked = tuple(
            RankedOpportunity(
                rank=index,
                candidate=candidate,
                qualification=qualification,
                score=score,
                components=components,
            )
            for index, (
                candidate,
                qualification,
                _robustness,
                components,
                score,
            ) in enumerate(qualified, start=1)
        )
        return OpportunityQueue(
            context_identifier=context.identifier,
            policy_version=self.policy.version,
            ranked=ranked,
            rejected=tuple(rejected),
        )

    def qualify(
        self,
        candidate: CandidateDecisionRecord,
        context: OpportunitySetContext,
    ) -> CandidateQualification:
        qualification, _ = self._qualify_with_robustness(candidate, context)
        return qualification

    def robustness(
        self,
        candidate: CandidateDecisionRecord,
        context: OpportunitySetContext,
    ) -> RobustCandidateAssessment:
        """Return the disclosed robustness assessment used by qualification."""

        _, robustness = self._qualify_with_robustness(candidate, context)
        return robustness

    def _qualify_with_robustness(
        self,
        candidate: CandidateDecisionRecord,
        context: OpportunitySetContext,
    ) -> tuple[CandidateQualification, RobustCandidateAssessment]:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if not isinstance(context, OpportunitySetContext):
            raise TypeError("context must be an OpportunitySetContext")
        if candidate.as_of != context.as_of:
            raise ValueError(
                "candidate and opportunity context must share an as_of timestamp"
            )

        universe = self.universe_policy.evaluate(candidate.instrument)
        baseline_alternatives = tuple(
            item
            for item in context.alternatives
            if item.kind is not AlternativeKind.QUALIFIED_CANDIDATE
        )
        if not baseline_alternatives:
            raise ValueError(
                "opportunity context must contain cash or a current holding"
            )
        comparable_alternatives = tuple(
            item
            for item in context.alternatives
            if not (
                item.kind is AlternativeKind.QUALIFIED_CANDIDATE
                and item.identifier == candidate.identifier
            )
        )
        if not comparable_alternatives:
            raise ValueError("candidate has no other available capital alternative")
        baseline_alternative = max(
            baseline_alternatives,
            key=lambda item: (
                item.net_expected_return,
                item.evidence_quality,
                item.liquidity_score,
                item.identifier,
            ),
        )
        best_alternative = max(
            comparable_alternatives,
            key=lambda item: (
                item.net_expected_return,
                item.evidence_quality,
                item.liquidity_score,
                item.identifier,
            ),
        )
        effective_opportunity_cost = best_alternative.net_expected_return
        opportunity_edge = round(
            candidate.net_expected_return - effective_opportunity_cost,
            8,
        )
        profile = self.policy_matrix.resolve(candidate)
        minimum_net_expected_return = self._profile_minimum(
            "minimum_net_expected_return",
            profile.minimum_net_expected_return,
        )
        minimum_opportunity_edge = self._profile_minimum(
            "minimum_opportunity_edge",
            profile.minimum_opportunity_edge,
        )
        minimum_probability = self._profile_minimum(
            "minimum_probability_of_success",
            profile.minimum_probability_of_success,
        )
        maximum_downside = self._profile_maximum_downside(
            profile.maximum_expected_downside
        )
        robustness = self.robust_assessor.assess(
            candidate,
            alternative_return=effective_opportunity_cost,
            policy_profile=profile,
        )
        # The disclosed edge retains its legacy arithmetic meaning for schema
        # compatibility. Qualification authority uses the horizon-normalized,
        # evidence-adjusted geometric edge below.
        holding_review = candidate.current_portfolio_weight > 0.0
        reasons: list[str] = []
        if not universe.direct_recommendation_allowed:
            reasons.extend(universe.reasons)
        if (
            abs(
                candidate.opportunity_cost_return
                - baseline_alternative.net_expected_return
            )
            > self.policy.opportunity_cost_tolerance
        ):
            reasons.append(
                "recorded candidate opportunity cost does not match the point-in-time opportunity set baseline alternatives"
            )
        if candidate.evidence_quality.score < self.policy.minimum_evidence_score:
            reasons.append("aggregate evidence quality is below threshold")
        if (
            candidate.evidence_quality.ceiling
            < self.policy.minimum_evidence_dimension
        ):
            reasons.append("at least one evidence-quality dimension is below threshold")
        if candidate.liquidity_score < self.policy.minimum_liquidity_score:
            reasons.append("candidate liquidity is below threshold")
        if (
            robustness.evidence_adjusted_return
            < minimum_net_expected_return
        ):
            reasons.append(
                "horizon-normalized evidence-adjusted expected return is below the absolute return threshold"
            )
        if robustness.robust_edge < minimum_opportunity_edge:
            reasons.append(
                "horizon-normalized opportunity edge is below the required margin"
            )
        scenario_downside = min(
            item.total_return for item in candidate.scenario_distribution
        ) - candidate.implementation_cost_return
        if scenario_downside < maximum_downside:
            reasons.append("expected downside exceeds the qualification limit")
        if (
            robustness.effective_probability_of_success
            < minimum_probability
        ):
            reasons.append(
                "scenario-derived probability of outperforming the best alternative is below threshold"
            )
        if (
            candidate.implementation_cost_return
            > self.policy.maximum_implementation_cost_return
        ):
            reasons.append("implementation costs exceed the qualification limit")
        if robustness.evidence_adjusted_return <= effective_opportunity_cost:
            reasons.append(
                "horizon-normalized expected return does not clear the best capital alternative"
            )
        reasons.extend(robustness.reasons)

        if holding_review:
            diagnostics = tuple(dict.fromkeys(reasons))
            return (
                CandidateQualification(
                    candidate_identifier=candidate.identifier,
                    outcome=QualificationOutcome.QUALIFIED,
                    policy_version=self.policy.version,
                    universe=universe,
                    effective_opportunity_cost=effective_opportunity_cost,
                    opportunity_edge=opportunity_edge,
                    best_alternative_identifier=best_alternative.identifier,
                    best_alternative_kind=best_alternative.kind,
                    baseline_alternative_identifier=baseline_alternative.identifier,
                    baseline_opportunity_cost=baseline_alternative.net_expected_return,
                    resolved_policy_profile=profile.identifier,
                    reasons=(
                        "current holdings receive mandatory specialist and CIO review even when they fail acquisition thresholds",
                        *diagnostics,
                    ),
                    analysis_lane=AnalysisLane.HOLDING_REVIEW,
                ),
                robustness,
            )

        if reasons:
            return (
                CandidateQualification(
                    candidate_identifier=candidate.identifier,
                    outcome=QualificationOutcome.REJECTED,
                    policy_version=self.policy.version,
                    universe=universe,
                    effective_opportunity_cost=effective_opportunity_cost,
                    opportunity_edge=opportunity_edge,
                    best_alternative_identifier=best_alternative.identifier,
                    best_alternative_kind=best_alternative.kind,
                    baseline_alternative_identifier=baseline_alternative.identifier,
                    baseline_opportunity_cost=baseline_alternative.net_expected_return,
                    resolved_policy_profile=profile.identifier,
                    reasons=tuple(dict.fromkeys(reasons)),
                ),
                robustness,
            )
        return (
            CandidateQualification(
                candidate_identifier=candidate.identifier,
                outcome=QualificationOutcome.QUALIFIED,
                policy_version=self.policy.version,
                universe=universe,
                effective_opportunity_cost=effective_opportunity_cost,
                opportunity_edge=opportunity_edge,
                best_alternative_identifier=best_alternative.identifier,
                best_alternative_kind=best_alternative.kind,
                baseline_alternative_identifier=baseline_alternative.identifier,
                resolved_policy_profile=profile.identifier,
                reasons=(
                    "candidate clears universe, absolute return, horizon-normalized geometric robustness, scenario-derived probability, downside, evidence, liquidity, cost, and opportunity-edge requirements; portfolio contribution remains subject to final construction",
                ),
            ),
            robustness,
        )


    def _profile_minimum(self, field_name: str, profile_value: float) -> float:
        """Use the matrix by default while preserving explicit stricter overrides."""

        configured = float(getattr(self.policy, field_name))
        default = float(getattr(self._default_policy, field_name))
        if abs(configured - default) <= 1e-12:
            return float(profile_value)
        return max(configured, float(profile_value))

    def _profile_maximum_downside(self, profile_value: float) -> float:
        configured = float(self.policy.maximum_expected_downside)
        default = float(self._default_policy.maximum_expected_downside)
        if abs(configured - default) <= 1e-12:
            return float(profile_value)
        return max(configured, float(profile_value))

    def _components(
        self,
        candidate: CandidateDecisionRecord,
        qualification: CandidateQualification,
        robustness: RobustCandidateAssessment,
        context: OpportunitySetContext,
    ) -> tuple[ScoreComponent, ...]:
        weights = self.policy.weights
        cost = candidate.implementation_cost_return
        probability_quality = (
            robustness.effective_probability_of_success
            * robustness.evidence_reliability
        )
        ranking = context.ranking_input(candidate.identifier)
        generated_default = ranking is None
        if ranking is None:
            ranking = self._default_ranking_input(candidate)
        portfolio_score = (
            0.50
            if generated_default
            else _clamp(
                0.65 * self._contribution_score(ranking.marginal_portfolio_contribution)
                + 0.35 * ranking.diversification_score
            )
        )
        raw_and_normalized = (
            (
                "net_expected_return",
                robustness.evidence_adjusted_return,
                _clamp((robustness.evidence_adjusted_return + 0.10) / 0.40),
            ),
            (
                "probability_of_success",
                probability_quality,
                _clamp(probability_quality),
            ),
            (
                "downside_protection",
                robustness.worst_case_portfolio_return,
                _clamp(
                    1.0
                    - abs(min(robustness.worst_case_portfolio_return, 0.0))
                    / abs(
                        self.robust_assessor.policy.minimum_worst_case_portfolio_return
                    )
                ),
            ),
            (
                "evidence_quality",
                candidate.evidence_quality.score,
                candidate.evidence_quality.score,
            ),
            (
                "evidence_freshness",
                candidate.evidence_quality.freshness,
                candidate.evidence_quality.freshness,
            ),
            (
                "evidence_independence",
                candidate.evidence_quality.independence,
                candidate.evidence_quality.independence,
            ),
            (
                "liquidity",
                candidate.liquidity_score,
                candidate.liquidity_score,
            ),
            (
                "opportunity_edge",
                robustness.stressed_edge,
                _clamp(robustness.stressed_edge / 0.20),
            ),
            (
                "portfolio_contribution",
                ranking.marginal_portfolio_contribution,
                portfolio_score,
            ),
            (
                "thesis_clarity",
                ranking.thesis_clarity_score,
                ranking.thesis_clarity_score,
            ),
            (
                "invalidation_clarity",
                ranking.invalidation_clarity_score,
                ranking.invalidation_clarity_score,
            ),
            (
                "forecast_durability",
                ranking.forecast_durability_score,
                ranking.forecast_durability_score,
            ),
            (
                "cost_efficiency",
                cost,
                _clamp(
                    1.0
                    - cost / self.policy.maximum_implementation_cost_return
                ),
            ),
        )
        return tuple(
            ScoreComponent(
                name=name,
                raw_value=raw_value,
                normalized_score=normalized,
                weight=weights[name],
            )
            for name, raw_value, normalized in raw_and_normalized
        )


    @staticmethod
    def _contribution_score(value: float) -> float:
        # Map a marginal annual portfolio-return contribution of -2%..+4% to 0..1.
        return _clamp((value + 0.02) / 0.06)

    @classmethod
    def _default_ranking_input(
        cls,
        candidate: CandidateDecisionRecord,
    ) -> OpportunityRankingInput:
        thesis = cls._clarity_score(
            candidate.primary_catalysts + candidate.critical_assumptions
        )
        invalidation = cls._clarity_score(candidate.invalidation_conditions)
        horizon = candidate.decision_horizon_days
        horizon_factor = min(1.0, max(0.20, horizon / 90.0))
        durability = _clamp(
            horizon_factor
            * (
                0.50 * candidate.evidence_quality.freshness
                + 0.30 * candidate.evidence_quality.completeness
                + 0.20 * candidate.evidence_quality.independence
            )
        )
        return OpportunityRankingInput(
            candidate_identifier=candidate.identifier,
            marginal_portfolio_contribution=0.0,
            diversification_score=0.50,
            thesis_clarity_score=thesis,
            invalidation_clarity_score=invalidation,
            forecast_durability_score=durability,
        )

    @staticmethod
    def _clarity_score(items: tuple[str, ...]) -> float:
        if not items:
            return 0.0
        measurable_tokens = (
            "above", "below", "increase", "decrease", "decline", "rise",
            "fall", "days", "month", "quarter", "%", "ratio", "spread",
            "growth", "margin", "price", "yield", "volume", "earnings",
        )
        scores = []
        for item in items:
            text = item.strip().lower()
            length = min(1.0, len(text.split()) / 10.0)
            measurable = 1.0 if any(token in text for token in measurable_tokens) else 0.35
            scores.append(0.45 * length + 0.55 * measurable)
        return _clamp(sum(scores) / len(scores))


__all__ = [
    "OpportunityEngine",
    "OpportunityQualificationPolicy",
]
