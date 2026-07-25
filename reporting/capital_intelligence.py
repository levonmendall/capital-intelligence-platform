"""Daily Capital Intelligence Score built from governed point-in-time results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from math import isclose
from typing import Any

from committee.regime_governance import RegimeCommitteeDecision
from economic_regime import Regime
from intelligence.recommendation import (
    ExpectedReturn,
    ExpectedRisk,
    RecommendationAction,
)
from intelligence.regime_pipeline import InstitutionalRegimeRun
from monitoring import MarketChangeAssessment
from portfolio import PortfolioFitDecision
from reporting.decision_card import build_cio_decision_card


_EXPECTED_RETURN_SCORES = {
    ExpectedReturn.VERY_LOW: 0.10,
    ExpectedReturn.LOW: 0.25,
    ExpectedReturn.MODERATE: 0.50,
    ExpectedReturn.HIGH: 0.75,
    ExpectedReturn.VERY_HIGH: 0.90,
}
_EXPECTED_RISK_SCORES = {
    ExpectedRisk.VERY_LOW: 0.10,
    ExpectedRisk.LOW: 0.25,
    ExpectedRisk.MODERATE: 0.45,
    ExpectedRisk.HIGH: 0.70,
    ExpectedRisk.VERY_HIGH: 0.90,
}
_RISK_LABELS = {
    ExpectedRisk.VERY_LOW: "Low",
    ExpectedRisk.LOW: "Low",
    ExpectedRisk.MODERATE: "Moderate",
    ExpectedRisk.HIGH: "Elevated",
    ExpectedRisk.VERY_HIGH: "High",
}


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _bounded(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return round(normalized, 6)


@dataclass(frozen=True, slots=True)
class CapitalIntelligenceScorePolicy:
    """Versioned and explainable score weights."""

    version: str = "capital-intelligence-score.v1"
    evidence_confidence_weight: float = 0.35
    data_coverage_weight: float = 0.10
    data_quality_weight: float = 0.10
    committee_support_weight: float = 0.20
    committee_agreement_weight: float = 0.10
    risk_adjusted_opportunity_weight: float = 0.15

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        fields = (
            "evidence_confidence_weight",
            "data_coverage_weight",
            "data_quality_weight",
            "committee_support_weight",
            "committee_agreement_weight",
            "risk_adjusted_opportunity_weight",
        )
        for field_name in fields:
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name=field_name),
            )
        if not isclose(
            sum(getattr(self, field_name) for field_name in fields),
            1.0,
            abs_tol=1e-6,
        ):
            raise ValueError("Capital Intelligence Score weights must sum to 1.0")


@dataclass(frozen=True, slots=True)
class CapitalIntelligenceComponents:
    """Normalized inputs that explain one daily score."""

    evidence_confidence: float
    data_coverage: float
    data_quality: float
    committee_support: float
    committee_agreement: float
    risk_adjusted_opportunity: float

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class CapitalIntelligenceScore:
    """One prominent daily number with simple supporting context."""

    identifier: str
    as_of: datetime
    score: int
    label: str
    environment: str
    risk: str
    committee: str
    portfolio_impact: str
    considerations: tuple[str, ...]
    policy_version: str
    components: CapitalIntelligenceComponents
    regime_run_identifier: str
    decision_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "label",
            "environment",
            "risk",
            "committee",
            "portfolio_impact",
            "policy_version",
            "regime_run_identifier",
            "decision_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise TypeError("score must be an int")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if not isinstance(self.components, CapitalIntelligenceComponents):
            raise TypeError("components must be CapitalIntelligenceComponents")
        if not isinstance(self.considerations, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.considerations
        ):
            raise TypeError("considerations must contain non-empty strings")


def environment_label_for_regime(regime: Regime) -> str:
    """Return a simple directional environment label."""

    if not isinstance(regime, Regime):
        raise TypeError("regime must be a Regime")
    if regime in {Regime.GOLDILOCKS, Regime.REFLATION}:
        return "Constructive"
    if regime in {Regime.STAGFLATION, Regime.CONTRACTION}:
        return "Defensive"
    if regime is Regime.DISINFLATIONARY_SLOWDOWN:
        return "Balanced"
    return "Uncertain"


def committee_vote_summary(decision: RegimeCommitteeDecision) -> str:
    """Compress committee statistics and recommendation direction."""

    if not isinstance(decision, RegimeCommitteeDecision):
        raise TypeError("decision must be a RegimeCommitteeDecision")
    if decision.committee_result is None:
        return "No vote — evidence gate held the decision"

    statistics = decision.committee_result.statistics
    target = decision.recommendation.target.replace("_", " ").title()
    if target in {"Diversified Risk Assets", "Broad Risk Assets"}:
        target = "Risk Assets"
    action = decision.recommendation.action
    verb = {
        RecommendationAction.OVERWEIGHT: "Favor",
        RecommendationAction.ACCUMULATE: "Add",
        RecommendationAction.UNDERWEIGHT: "Underweight",
        RecommendationAction.REDUCE: "Reduce",
        RecommendationAction.AVOID: "Avoid",
        RecommendationAction.NEUTRAL: "Hold",
    }[action]
    tally = f"{statistics.supportive_count}–{statistics.opposed_count}"
    if statistics.neutral_count:
        tally += f", {statistics.neutral_count} neutral"
    return f"{tally} {verb} {target}"


def _score_label(score: int) -> str:
    if score >= 90:
        return "Exceptional clarity"
    if score >= 80:
        return "Strong"
    if score >= 65:
        return "Clear"
    if score >= 50:
        return "Mixed"
    return "Limited"


def build_capital_intelligence_score(
    run: InstitutionalRegimeRun,
    decision: RegimeCommitteeDecision,
    *,
    change: MarketChangeAssessment | None = None,
    portfolio_fit: PortfolioFitDecision | None = None,
    policy: CapitalIntelligenceScorePolicy | None = None,
) -> CapitalIntelligenceScore:
    """Build the daily score without changing any underlying decision."""

    if not isinstance(run, InstitutionalRegimeRun):
        raise TypeError("run must be an InstitutionalRegimeRun")
    if not isinstance(decision, RegimeCommitteeDecision):
        raise TypeError("decision must be a RegimeCommitteeDecision")
    resolved_policy = policy or CapitalIntelligenceScorePolicy()
    card = build_cio_decision_card(
        run,
        decision,
        change=change,
        portfolio_fit=portfolio_fit,
    )
    evidence = run.assessment.evidence
    statistics = (
        decision.committee_result.statistics
        if decision.committee_result is not None
        else None
    )
    opportunity = max(
        0.0,
        _EXPECTED_RETURN_SCORES[decision.recommendation.expected_return]
        - _EXPECTED_RISK_SCORES[decision.recommendation.expected_risk],
    )
    components = CapitalIntelligenceComponents(
        evidence_confidence=run.assessment.confidence,
        data_coverage=evidence.data_coverage,
        data_quality=evidence.quality_score,
        committee_support=(statistics.support_ratio if statistics else 0.0),
        committee_agreement=(statistics.agreement_score if statistics else 0.0),
        risk_adjusted_opportunity=opportunity,
    )
    weighted = (
        components.evidence_confidence
        * resolved_policy.evidence_confidence_weight
        + components.data_coverage * resolved_policy.data_coverage_weight
        + components.data_quality * resolved_policy.data_quality_weight
        + components.committee_support
        * resolved_policy.committee_support_weight
        + components.committee_agreement
        * resolved_policy.committee_agreement_weight
        + components.risk_adjusted_opportunity
        * resolved_policy.risk_adjusted_opportunity_weight
    )
    score = round(weighted * 100)
    considerations = tuple(
        f"Review {exposure}." for exposure in card.affected_exposures[:2]
    )
    return CapitalIntelligenceScore(
        identifier=f"capital-intelligence:{run.as_of.isoformat()}",
        as_of=run.as_of,
        score=score,
        label=_score_label(score),
        environment=environment_label_for_regime(run.assessment.result.regime),
        risk=_RISK_LABELS[decision.recommendation.expected_risk],
        committee=committee_vote_summary(decision),
        portfolio_impact=card.decision,
        considerations=considerations,
        policy_version=resolved_policy.version,
        components=components,
        regime_run_identifier=decision.regime_run_identifier,
        decision_identifier=decision.decision_identifier,
    )


def capital_intelligence_score_to_dict(
    result: CapitalIntelligenceScore,
) -> dict[str, Any]:
    """Return the stable client representation of the daily score."""

    if not isinstance(result, CapitalIntelligenceScore):
        raise TypeError("result must be a CapitalIntelligenceScore")
    return {
        "schema_version": "capital-intelligence-score.v1",
        "identifier": result.identifier,
        "as_of": result.as_of.isoformat(),
        "score": result.score,
        "label": result.label,
        "environment": result.environment,
        "risk": result.risk,
        "committee": result.committee,
        "portfolio_impact": result.portfolio_impact,
        "considerations": list(result.considerations),
        "policy_version": result.policy_version,
        "components": {
            field_name: getattr(result.components, field_name)
            for field_name in result.components.__dataclass_fields__
        },
        "sources": {
            "regime_run": result.regime_run_identifier,
            "decision": result.decision_identifier,
        },
    }


def render_capital_intelligence_score_json(
    result: CapitalIntelligenceScore,
) -> str:
    return json.dumps(
        capital_intelligence_score_to_dict(result),
        indent=2,
        sort_keys=True,
    )


def render_capital_intelligence_score_markdown(
    result: CapitalIntelligenceScore,
) -> str:
    """Render the compact morning identity surface."""

    lines = [
        "# Today's Capital Intelligence",
        "",
        f"## {result.score}",
        result.label,
        "",
        f"**Environment:** {result.environment}",
        f"**Risk:** {result.risk}",
        f"**Committee:** {result.committee}",
        f"**Portfolio impact:** {result.portfolio_impact}",
    ]
    if result.considerations:
        lines.extend(
            (
                "",
                "**Consider:**",
                *[f"- {item}" for item in result.considerations],
            )
        )
    return "\n".join(lines)


__all__ = [
    "CapitalIntelligenceComponents",
    "CapitalIntelligenceScore",
    "CapitalIntelligenceScorePolicy",
    "build_capital_intelligence_score",
    "capital_intelligence_score_to_dict",
    "committee_vote_summary",
    "environment_label_for_regime",
    "render_capital_intelligence_score_json",
    "render_capital_intelligence_score_markdown",
]
