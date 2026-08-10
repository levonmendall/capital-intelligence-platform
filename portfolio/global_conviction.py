"""Graduated CIO participation policy for globally ranked opportunities.

Hard readiness/integrity/risk failures remain zero-capital boundaries. Ordinary
forecast uncertainty, posture disagreement, persistence, and bounded specialist
dissent reduce conviction and size instead of automatically converting to cash.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from portfolio.global_rotation_models import GlobalOpportunitySignal


class ConvictionStage(str, Enum):
    BLOCKED = "blocked"
    ECONOMICALLY_INFERIOR = "economically_inferior"
    UNRESOLVED = "unresolved"
    EXPLORATORY = "exploratory"
    PROVISIONAL = "provisional"
    QUALIFIED = "qualified"
    HIGH_CONVICTION = "high_conviction"


@dataclass(frozen=True, slots=True)
class GlobalConvictionDecision:
    stage: ConvictionStage
    target_weight: float | None
    hard_blockers: tuple[str, ...]
    soft_constraints: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def authorized(self) -> bool:
        return (
            self.target_weight is not None
            and self.target_weight > 0.0
            and self.stage
            in {
                ConvictionStage.EXPLORATORY,
                ConvictionStage.PROVISIONAL,
                ConvictionStage.QUALIFIED,
                ConvictionStage.HIGH_CONVICTION,
            }
        )


@dataclass(frozen=True, slots=True)
class GlobalConvictionPolicy:
    version: str = "global-conviction-ladder.v1"
    exploratory_minimum_weight: float = 0.0025
    exploratory_maximum_weight: float = 0.01
    provisional_maximum_weight: float = 0.03
    qualified_reference_weight: float = 0.07
    high_conviction_reference_weight: float = 0.10
    exploratory_minimum_score: float = 0.40
    provisional_minimum_score: float = 0.55
    high_conviction_minimum_score: float = 0.78
    exploratory_minimum_probability: float = 0.45
    provisional_minimum_probability: float = 0.48
    high_conviction_minimum_probability: float = 0.60
    exploratory_maximum_probability_of_loss: float = 0.60
    provisional_maximum_probability_of_loss: float = 0.55
    exploratory_minimum_stressed_edge: float = 0.0
    provisional_minimum_stressed_edge: float = 0.0

    def _hard_blockers(
        self,
        *,
        candidate: object,
        universe: object,
        specialists: object,
        robustness: object,
        reconciliation: object,
        profile: object,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not bool(getattr(universe, "direct_recommendation_allowed", False)):
            reasons.append("capability authority prohibits new direct exposure")
        vetoes = tuple(getattr(specialists, "evidence_vetoes", ()) or ())
        if vetoes:
            reasons.append("evidence governance vetoes remain unresolved")
        implementation = tuple(getattr(specialists, "implementation_blocks", ()) or ())
        if implementation:
            reasons.append("portfolio implementation blocks remain unresolved")
        quality = getattr(candidate, "evidence_quality", None)
        if quality is None or float(getattr(quality, "score", 0.0)) < 0.70:
            reasons.append("aggregate evidence quality is below 70%")
        if quality is None or float(getattr(quality, "ceiling", 0.0)) < 0.50:
            reasons.append("a required evidence dimension is below 50%")
        if float(getattr(reconciliation, "expected_downside", -1.0)) < float(
            getattr(profile, "maximum_expected_downside", 0.0)
        ):
            reasons.append("reconciled downside exceeds the applicable hard risk limit")
        hard_markers = (
            "scenario ordering",
            "non-positive portfolio wealth",
            "inconsistent with the disclosed scenarios",
            "worst-case portfolio loss",
            "reconciled scenario path drawdown exceeds",
        )
        for reason in tuple(getattr(robustness, "reasons", ()) or ()):
            if any(marker in str(reason) for marker in hard_markers):
                reasons.append(str(reason))
        portfolio = getattr(specialists, "portfolio_recommendation", None)
        recommended = getattr(portfolio, "recommended_position_weight", None)
        funding = getattr(portfolio, "funding_source", None)
        if recommended is None or float(recommended) <= 0.0:
            reasons.append("portfolio specialist found no positive feasible weight")
        if not isinstance(funding, str) or not funding.strip():
            reasons.append("portfolio specialist identified no exact funding source")
        return tuple(dict.fromkeys(reasons))

    def assess(
        self,
        *,
        candidate: object,
        signal: GlobalOpportunitySignal | None,
        universe: object,
        specialists: object,
        robustness: object,
        reconciliation: object,
        profile: object,
        ensemble: object,
        directive: object | None,
        material_opposition_threshold: float,
    ) -> GlobalConvictionDecision:
        hard = self._hard_blockers(
            candidate=candidate,
            universe=universe,
            specialists=specialists,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
        )
        if hard:
            return GlobalConvictionDecision(
                ConvictionStage.BLOCKED,
                None,
                hard,
                (),
                ("hard readiness, implementation, or risk controls prohibit positive capital",),
            )

        horizon_alternative = float(
            getattr(reconciliation, "horizon_alternative_return", 0.0)
        )
        expected = float(getattr(reconciliation, "expected_return", -1.0))
        robust_edge = float(getattr(robustness, "robust_edge", -1.0))
        if expected <= horizon_alternative or robust_edge <= 0.0:
            return GlobalConvictionDecision(
                ConvictionStage.ECONOMICALLY_INFERIOR,
                None,
                (),
                (),
                ("the candidate does not currently beat the best governed capital alternative",),
            )

        score = 0.0 if signal is None else signal.score
        success = float(
            getattr(robustness, "effective_probability_of_success", 0.0)
        )
        stressed = float(getattr(robustness, "stressed_edge", -1.0))
        probability_loss = float(getattr(robustness, "probability_of_loss", 1.0))
        soft: list[str] = []
        if success < float(getattr(profile, "minimum_probability_of_success", 1.0)):
            soft.append("success probability is below the full-conviction threshold")
        if float(getattr(robustness, "evidence_adjusted_return", -1.0)) < float(
            getattr(profile, "minimum_net_expected_return", 1.0)
        ):
            soft.append("evidence-adjusted return is below the full-conviction threshold")
        if robust_edge < float(getattr(profile, "minimum_opportunity_edge", 1.0)):
            soft.append("robust edge is below the full-conviction margin")
        if stressed <= 0.0:
            soft.append("adverse probability stress removes the full-conviction edge")

        opposition = 0
        counter = getattr(specialists, "independent_opposition_count", None)
        if callable(counter):
            opposition = int(counter(float(material_opposition_threshold)))
        if opposition:
            soft.append(
                f"{opposition} independent high-confidence specialist objection(s) remain"
            )
        ensemble_stage = str(
            getattr(getattr(ensemble, "stage", None), "value", "observe")
        )
        if ensemble_stage == "observe":
            soft.append("growth ensemble remains at observe")
        if directive is not None:
            if bool(getattr(directive, "discouraged", False)):
                soft.append("current portfolio posture discourages this sleeve")
            elif not bool(getattr(directive, "preferred", False)):
                soft.append("current portfolio posture does not prefer this sleeve")

        full = (
            success >= float(getattr(profile, "minimum_probability_of_success", 1.0))
            and float(getattr(robustness, "evidence_adjusted_return", -1.0))
            >= float(getattr(profile, "minimum_net_expected_return", 1.0))
            and robust_edge >= float(getattr(profile, "minimum_opportunity_edge", 1.0))
            and stressed > 0.0
        )
        if (
            full
            and score >= self.high_conviction_minimum_score
            and success >= self.high_conviction_minimum_probability
        ):
            stage = ConvictionStage.HIGH_CONVICTION
        elif full:
            stage = ConvictionStage.QUALIFIED
        elif (
            score >= self.provisional_minimum_score
            and success >= self.provisional_minimum_probability
            and probability_loss <= self.provisional_maximum_probability_of_loss
            and stressed >= self.provisional_minimum_stressed_edge
        ):
            stage = ConvictionStage.PROVISIONAL
        elif (
            score >= self.exploratory_minimum_score
            and success >= self.exploratory_minimum_probability
            and probability_loss <= self.exploratory_maximum_probability_of_loss
            and stressed >= self.exploratory_minimum_stressed_edge
        ):
            stage = ConvictionStage.EXPLORATORY
        else:
            return GlobalConvictionDecision(
                ConvictionStage.UNRESOLVED,
                None,
                (),
                tuple(dict.fromkeys(soft)),
                (
                    "positive economics survive, but uncertainty is too high for even "
                    "the exploratory risk budget"
                ),
            )

        # Multiple independent objections, an observe ensemble, or a discouraged
        # posture reduce size; they do not become hidden zero-target vetoes.
        if (
            opposition >= 2
            or ensemble_stage == "observe"
            or bool(getattr(directive, "discouraged", False))
        ):
            stage = ConvictionStage.EXPLORATORY
        elif opposition >= 1 and stage in {
            ConvictionStage.HIGH_CONVICTION,
            ConvictionStage.QUALIFIED,
        }:
            stage = ConvictionStage.PROVISIONAL
        elif (
            directive is not None
            and not bool(getattr(directive, "preferred", False))
            and stage is ConvictionStage.HIGH_CONVICTION
        ):
            stage = ConvictionStage.QUALIFIED

        portfolio = getattr(specialists, "portfolio_recommendation")
        maximum = min(
            float(getattr(candidate, "maximum_position_weight", 0.0)),
            float(getattr(profile, "maximum_position_weight", 0.0)),
            float(getattr(portfolio, "recommended_position_weight", 0.0)),
        )
        multiplier = float(
            getattr(
                getattr(specialists, "historical_learning", None),
                "effective_position_multiplier",
                1.0,
            )
        )
        maximum *= max(0.0, min(1.0, multiplier))
        if opposition >= 3:
            maximum = min(maximum, 0.005)
        if stage is ConvictionStage.EXPLORATORY:
            desired = max(
                self.exploratory_minimum_weight,
                self.exploratory_maximum_weight * max(0.50, score),
            )
            target = min(maximum, self.exploratory_maximum_weight, desired)
        elif stage is ConvictionStage.PROVISIONAL:
            normalized = max(
                0.0,
                min(
                    1.0,
                    (score - self.provisional_minimum_score) / 0.23,
                ),
            )
            target = min(
                maximum,
                self.provisional_maximum_weight,
                0.01 + 0.02 * normalized,
            )
        elif stage is ConvictionStage.QUALIFIED:
            target = min(maximum, self.qualified_reference_weight)
        else:
            target = min(maximum, self.high_conviction_reference_weight)
        if target <= 0.0:
            return GlobalConvictionDecision(
                ConvictionStage.BLOCKED,
                None,
                ("no positive target survives the complete sizing boundary",),
                tuple(dict.fromkeys(soft)),
                ("all candidate, portfolio, policy, and learning caps resolve to zero",),
            )
        return GlobalConvictionDecision(
            stage,
            round(target, 8),
            (),
            tuple(dict.fromkeys(soft)),
            (
                f"{stage.value} participation expresses surviving opportunity through "
                "bounded position size"
            ),
        )


__all__ = [
    "ConvictionStage",
    "GlobalConvictionDecision",
    "GlobalConvictionPolicy",
]
