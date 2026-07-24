"""Continuous regime analysis with portfolio-relevant alert suppression."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite

from committee.regime_governance import (
    RegimeCommitteeDecision,
    RegimeGovernanceOutcome,
)
from economic_regime import Regime
from intelligence.recommendation import RecommendationAction
from intelligence.regime_pipeline import InstitutionalRegimeRun


class ChangeCategory(str, Enum):
    """Analytical dimension that changed between two market runs."""

    REGIME = "regime"
    RECOMMENDATION = "recommendation"
    GOVERNANCE = "governance"
    DATA_QUALITY = "data_quality"
    CONFIDENCE = "confidence"
    SIGNAL = "signal"


class ChangeSeverity(str, Enum):
    """Materiality of one observed change."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewState(str, Enum):
    """Whether new evidence warrants portfolio reconsideration."""

    UNCHANGED = "unchanged"
    MONITOR = "monitor"
    REVIEW_REQUIRED = "review_required"
    PRIOR_VIEW_INVALIDATED = "prior_view_invalidated"


class AlertLevel(str, Enum):
    """Notification decision kept separate from continuous analysis."""

    SILENT = "silent"
    NOTIFY = "notify"
    URGENT = "urgent"


class PortfolioImpactDirection(str, Enum):
    """Directional implication before mandate-aware position sizing."""

    HOLD = "hold"
    REVIEW = "review"
    INCREASE_RISK = "increase_risk"
    REDUCE_RISK = "reduce_risk"
    REBALANCE = "rebalance"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class MaterialChangePolicy:
    """Versioned thresholds separating analysis from notification."""

    version: str = "material-change.v1"
    signal_score_delta: float = 0.25
    confidence_delta: float = 0.10
    quality_delta: float = 0.20
    minimum_data_coverage: float = 0.80
    minimum_quality_score: float = 0.75
    minimum_evidence_confidence: float = 0.55
    stress_review_threshold: float = 0.45
    growth_contraction_threshold: float = -0.45
    medium_changes_for_review: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        for field_name in (
            "signal_score_delta",
            "confidence_delta",
            "quality_delta",
            "minimum_data_coverage",
            "minimum_quality_score",
            "minimum_evidence_confidence",
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
        for field_name in (
            "stress_review_threshold",
            "growth_contraction_threshold",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or not -1.0 <= normalized <= 1.0:
                raise ValueError(
                    f"{field_name} must be between -1.0 and 1.0"
                )
            object.__setattr__(self, field_name, normalized)
        if (
            isinstance(self.medium_changes_for_review, bool)
            or not isinstance(self.medium_changes_for_review, int)
        ):
            raise TypeError("medium_changes_for_review must be an int")
        if self.medium_changes_for_review < 1:
            raise ValueError(
                "medium_changes_for_review must be positive"
            )


@dataclass(frozen=True, slots=True)
class MaterialChange:
    """One auditable difference between consecutive analyses."""

    category: ChangeCategory
    severity: ChangeSeverity
    summary: str
    previous_value: str
    current_value: str
    portfolio_relevant: bool

    def __post_init__(self) -> None:
        if not isinstance(self.category, ChangeCategory):
            raise TypeError("category must be a ChangeCategory")
        if not isinstance(self.severity, ChangeSeverity):
            raise TypeError("severity must be a ChangeSeverity")
        for field_name in (
            "summary",
            "previous_value",
            "current_value",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if not isinstance(self.portfolio_relevant, bool):
            raise TypeError("portfolio_relevant must be a bool")


@dataclass(frozen=True, slots=True)
class PortfolioImpact:
    """Plain-language directional effect on a model portfolio."""

    direction: PortfolioImpactDirection
    affected_exposures: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(
            self.direction,
            PortfolioImpactDirection,
        ):
            raise TypeError(
                "direction must be a PortfolioImpactDirection"
            )
        if not isinstance(self.affected_exposures, tuple):
            raise TypeError("affected_exposures must be a tuple")
        normalized = tuple(
            _required_text(value, field_name="affected_exposures")
            for value in self.affected_exposures
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError(
                "affected_exposures cannot contain duplicates"
            )
        object.__setattr__(
            self,
            "affected_exposures",
            normalized,
        )
        object.__setattr__(
            self,
            "explanation",
            _required_text(
                self.explanation,
                field_name="explanation",
            ),
        )


@dataclass(frozen=True, slots=True)
class MarketChangeAssessment:
    """Every comparison is recorded; only important ones notify."""

    identifier: str
    previous_as_of: datetime
    current_as_of: datetime
    analyzed_at: datetime
    policy_version: str
    state: ReviewState
    alert_level: AlertLevel
    headline: str
    explanation: str
    changes: tuple[MaterialChange, ...]
    portfolio_impact: PortfolioImpact

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "policy_version",
            "headline",
            "explanation",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        for field_name in (
            "previous_as_of",
            "current_as_of",
            "analyzed_at",
        ):
            _aware_datetime(
                getattr(self, field_name),
                field_name=field_name,
            )
        if self.current_as_of <= self.previous_as_of:
            raise ValueError(
                "current_as_of must be later than previous_as_of"
            )
        if not isinstance(self.state, ReviewState):
            raise TypeError("state must be a ReviewState")
        if not isinstance(self.alert_level, AlertLevel):
            raise TypeError("alert_level must be an AlertLevel")
        if not isinstance(self.changes, tuple) or not all(
            isinstance(change, MaterialChange)
            for change in self.changes
        ):
            raise TypeError(
                "changes must contain MaterialChange values"
            )
        if not isinstance(self.portfolio_impact, PortfolioImpact):
            raise TypeError(
                "portfolio_impact must be a PortfolioImpact"
            )
        if (
            self.state
            in {
                ReviewState.UNCHANGED,
                ReviewState.MONITOR,
            }
            and self.alert_level is not AlertLevel.SILENT
        ):
            raise ValueError(
                "unchanged and monitor states must remain silent"
            )
        if (
            self.state is ReviewState.REVIEW_REQUIRED
            and self.alert_level is not AlertLevel.NOTIFY
        ):
            raise ValueError(
                "review_required must use notify alert level"
            )
        if (
            self.state is ReviewState.PRIOR_VIEW_INVALIDATED
            and self.alert_level is not AlertLevel.URGENT
        ):
            raise ValueError(
                "prior_view_invalidated must use urgent alert level"
            )

    @property
    def should_alert(self) -> bool:
        """Whether a delivery layer should notify the user."""

        return self.alert_level is not AlertLevel.SILENT


_SEVERITY_RANK = {
    ChangeSeverity.LOW: 1,
    ChangeSeverity.MEDIUM: 2,
    ChangeSeverity.HIGH: 3,
    ChangeSeverity.CRITICAL: 4,
}

_REGIME_EXPOSURES = {
    Regime.GOLDILOCKS: (
        "equities",
        "credit",
        "crypto risk budget",
    ),
    Regime.REFLATION: (
        "cyclical equities",
        "commodities",
        "duration",
        "crypto risk budget",
    ),
    Regime.STAGFLATION: (
        "equities",
        "duration",
        "inflation hedges",
        "cash",
    ),
    Regime.DISINFLATIONARY_SLOWDOWN: (
        "duration",
        "equities",
        "cash",
        "crypto risk budget",
    ),
    Regime.CONTRACTION: (
        "equities",
        "credit",
        "cash",
        "crypto risk budget",
    ),
    Regime.TRANSITION: (
        "portfolio risk budget",
    ),
}


class RegimeMaterialChangeEngine:
    """Analyze every new run and suppress non-actionable alerts."""

    def __init__(
        self,
        policy: MaterialChangePolicy | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy or MaterialChangePolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def compare(
        self,
        previous_run: InstitutionalRegimeRun,
        current_run: InstitutionalRegimeRun,
        previous_decision: RegimeCommitteeDecision,
        current_decision: RegimeCommitteeDecision,
    ) -> MarketChangeAssessment:
        """Compare consecutive analyses and decide whether to alert."""

        self._validate_inputs(
            previous_run,
            current_run,
            previous_decision,
            current_decision,
        )
        analyzed_at = _aware_datetime(
            self._clock(),
            field_name="clock",
        )
        changes: list[MaterialChange] = []
        self._regime_changes(
            previous_run,
            current_run,
            changes,
        )
        self._recommendation_changes(
            previous_decision,
            current_decision,
            changes,
        )
        self._governance_changes(
            previous_decision,
            current_decision,
            changes,
        )
        self._quality_changes(
            previous_run,
            current_run,
            changes,
        )
        self._confidence_changes(
            previous_run,
            current_run,
            changes,
        )
        self._signal_changes(
            previous_run,
            current_run,
            changes,
        )
        state, alert_level = self._disposition(tuple(changes))
        impact = self._portfolio_impact(
            current_run,
            current_decision,
            state,
        )
        headline, explanation = self._simple_explanation(
            state,
            impact.direction,
        )
        return MarketChangeAssessment(
            identifier=(
                "market-change:"
                f"{previous_run.as_of.isoformat()}:"
                f"{current_run.as_of.isoformat()}"
            ),
            previous_as_of=previous_run.as_of,
            current_as_of=current_run.as_of,
            analyzed_at=analyzed_at,
            policy_version=self.policy.version,
            state=state,
            alert_level=alert_level,
            headline=headline,
            explanation=explanation,
            changes=tuple(changes),
            portfolio_impact=impact,
        )

    @staticmethod
    def _validate_inputs(
        previous_run: InstitutionalRegimeRun,
        current_run: InstitutionalRegimeRun,
        previous_decision: RegimeCommitteeDecision,
        current_decision: RegimeCommitteeDecision,
    ) -> None:
        if not isinstance(previous_run, InstitutionalRegimeRun):
            raise TypeError(
                "previous_run must be an InstitutionalRegimeRun"
            )
        if not isinstance(current_run, InstitutionalRegimeRun):
            raise TypeError(
                "current_run must be an InstitutionalRegimeRun"
            )
        if current_run.as_of <= previous_run.as_of:
            raise ValueError(
                "current_run must be later than previous_run"
            )
        if not isinstance(
            previous_decision,
            RegimeCommitteeDecision,
        ):
            raise TypeError(
                "previous_decision must be a "
                "RegimeCommitteeDecision"
            )
        if not isinstance(
            current_decision,
            RegimeCommitteeDecision,
        ):
            raise TypeError(
                "current_decision must be a RegimeCommitteeDecision"
            )
        if (
            previous_run.as_of.isoformat()
            not in previous_decision.recommendation.identifier
        ):
            raise ValueError(
                "previous_decision must reference previous_run"
            )
        if (
            current_run.as_of.isoformat()
            not in current_decision.recommendation.identifier
        ):
            raise ValueError(
                "current_decision must reference current_run"
            )

    @staticmethod
    def _add(
        changes: list[MaterialChange],
        *,
        category: ChangeCategory,
        severity: ChangeSeverity,
        summary: str,
        previous_value: object,
        current_value: object,
        portfolio_relevant: bool = True,
    ) -> None:
        changes.append(
            MaterialChange(
                category=category,
                severity=severity,
                summary=summary,
                previous_value=str(previous_value),
                current_value=str(current_value),
                portfolio_relevant=portfolio_relevant,
            )
        )

    def _regime_changes(
        self,
        previous: InstitutionalRegimeRun,
        current: InstitutionalRegimeRun,
        changes: list[MaterialChange],
    ) -> None:
        previous_regime = previous.assessment.result.regime
        current_regime = current.assessment.result.regime
        if previous_regime is current_regime:
            return
        severity = (
            ChangeSeverity.CRITICAL
            if current_regime
            in {Regime.CONTRACTION, Regime.STAGFLATION}
            else ChangeSeverity.HIGH
        )
        self._add(
            changes,
            category=ChangeCategory.REGIME,
            severity=severity,
            summary="The economic regime changed.",
            previous_value=previous_regime.value,
            current_value=current_regime.value,
        )

    def _recommendation_changes(
        self,
        previous: RegimeCommitteeDecision,
        current: RegimeCommitteeDecision,
        changes: list[MaterialChange],
    ) -> None:
        previous_recommendation = previous.recommendation
        current_recommendation = current.recommendation
        if (
            previous_recommendation.action
            is not current_recommendation.action
        ):
            self._add(
                changes,
                category=ChangeCategory.RECOMMENDATION,
                severity=ChangeSeverity.HIGH,
                summary="The recommended portfolio action changed.",
                previous_value=previous_recommendation.action.value,
                current_value=current_recommendation.action.value,
            )
        if previous_recommendation.target != current_recommendation.target:
            self._add(
                changes,
                category=ChangeCategory.RECOMMENDATION,
                severity=ChangeSeverity.HIGH,
                summary="The affected portfolio exposure changed.",
                previous_value=previous_recommendation.target,
                current_value=current_recommendation.target,
            )

    def _governance_changes(
        self,
        previous: RegimeCommitteeDecision,
        current: RegimeCommitteeDecision,
        changes: list[MaterialChange],
    ) -> None:
        if previous.outcome is current.outcome:
            return
        restrictive = {
            RegimeGovernanceOutcome.REJECT,
            RegimeGovernanceOutcome.ESCALATE,
            RegimeGovernanceOutcome.NO_ACTION,
        }
        self._add(
            changes,
            category=ChangeCategory.GOVERNANCE,
            severity=(
                ChangeSeverity.HIGH
                if current.outcome in restrictive
                else ChangeSeverity.MEDIUM
            ),
            summary="The committee decision changed.",
            previous_value=previous.outcome.value,
            current_value=current.outcome.value,
        )

    def _quality_changes(
        self,
        previous: InstitutionalRegimeRun,
        current: InstitutionalRegimeRun,
        changes: list[MaterialChange],
    ) -> None:
        previous_evidence = previous.assessment.evidence
        current_evidence = current.assessment.evidence
        coverage_drop = (
            previous_evidence.data_coverage
            - current_evidence.data_coverage
        )
        quality_drop = (
            previous_evidence.quality_score
            - current_evidence.quality_score
        )
        coverage_crossed = (
            previous_evidence.data_coverage
            >= self.policy.minimum_data_coverage
            > current_evidence.data_coverage
        )
        quality_crossed = (
            previous_evidence.quality_score
            >= self.policy.minimum_quality_score
            > current_evidence.quality_score
        )
        if coverage_crossed or coverage_drop >= self.policy.quality_delta:
            self._add(
                changes,
                category=ChangeCategory.DATA_QUALITY,
                severity=(
                    ChangeSeverity.HIGH
                    if coverage_crossed
                    else ChangeSeverity.MEDIUM
                ),
                summary="Market evidence coverage fell.",
                previous_value=f"{previous_evidence.data_coverage:.0%}",
                current_value=f"{current_evidence.data_coverage:.0%}",
            )
        if quality_crossed or quality_drop >= self.policy.quality_delta:
            self._add(
                changes,
                category=ChangeCategory.DATA_QUALITY,
                severity=(
                    ChangeSeverity.HIGH
                    if quality_crossed
                    else ChangeSeverity.MEDIUM
                ),
                summary="Market evidence quality fell.",
                previous_value=f"{previous_evidence.quality_score:.0%}",
                current_value=f"{current_evidence.quality_score:.0%}",
            )

    def _confidence_changes(
        self,
        previous: InstitutionalRegimeRun,
        current: InstitutionalRegimeRun,
        changes: list[MaterialChange],
    ) -> None:
        previous_confidence = previous.assessment.confidence
        current_confidence = current.assessment.confidence
        delta = current_confidence - previous_confidence
        crossed = (
            previous_confidence
            >= self.policy.minimum_evidence_confidence
            > current_confidence
        )
        if abs(delta) < self.policy.confidence_delta and not crossed:
            return
        self._add(
            changes,
            category=ChangeCategory.CONFIDENCE,
            severity=(
                ChangeSeverity.HIGH
                if crossed
                else ChangeSeverity.MEDIUM
            ),
            summary=(
                "Confidence in the market view fell."
                if delta < 0
                else "Confidence in the market view improved."
            ),
            previous_value=f"{previous_confidence:.0%}",
            current_value=f"{current_confidence:.0%}",
        )

    def _signal_changes(
        self,
        previous: InstitutionalRegimeRun,
        current: InstitutionalRegimeRun,
        changes: list[MaterialChange],
    ) -> None:
        previous_signals = {
            signal.name.value: signal.score
            for signal in previous.assessment.evidence.signals
        }
        current_signals = {
            signal.name.value: signal.score
            for signal in current.assessment.evidence.signals
        }
        for name in sorted(previous_signals):
            previous_score = previous_signals[name]
            current_score = current_signals[name]
            if previous_score is None or current_score is None:
                continue
            delta = current_score - previous_score
            crossed_band = (
                self._signal_band(previous_score)
                != self._signal_band(current_score)
            )
            if (
                abs(delta) < self.policy.signal_score_delta
                and not crossed_band
            ):
                continue
            severity = ChangeSeverity.MEDIUM
            if (
                name == "financial_stress"
                and previous_score
                < self.policy.stress_review_threshold
                <= current_score
            ):
                severity = ChangeSeverity.CRITICAL
            elif (
                name == "growth"
                and previous_score
                > self.policy.growth_contraction_threshold
                >= current_score
            ):
                severity = ChangeSeverity.CRITICAL
            self._add(
                changes,
                category=ChangeCategory.SIGNAL,
                severity=severity,
                summary=(
                    f"{name.replace('_', ' ').capitalize()} "
                    "changed materially."
                ),
                previous_value=f"{previous_score:+.2f}",
                current_value=f"{current_score:+.2f}",
            )

    @staticmethod
    def _signal_band(value: float) -> int:
        if value >= 0.25:
            return 1
        if value <= -0.25:
            return -1
        return 0

    def _disposition(
        self,
        changes: tuple[MaterialChange, ...],
    ) -> tuple[ReviewState, AlertLevel]:
        if not changes:
            return ReviewState.UNCHANGED, AlertLevel.SILENT
        portfolio_changes = tuple(
            change for change in changes if change.portfolio_relevant
        )
        highest = max(
            (
                _SEVERITY_RANK[change.severity]
                for change in portfolio_changes
            ),
            default=0,
        )
        if highest >= _SEVERITY_RANK[ChangeSeverity.CRITICAL]:
            return (
                ReviewState.PRIOR_VIEW_INVALIDATED,
                AlertLevel.URGENT,
            )
        if highest >= _SEVERITY_RANK[ChangeSeverity.HIGH]:
            return ReviewState.REVIEW_REQUIRED, AlertLevel.NOTIFY
        medium_count = sum(
            change.severity is ChangeSeverity.MEDIUM
            for change in portfolio_changes
        )
        if medium_count >= self.policy.medium_changes_for_review:
            return ReviewState.REVIEW_REQUIRED, AlertLevel.NOTIFY
        return ReviewState.MONITOR, AlertLevel.SILENT

    def _portfolio_impact(
        self,
        current_run: InstitutionalRegimeRun,
        current_decision: RegimeCommitteeDecision,
        state: ReviewState,
    ) -> PortfolioImpact:
        if state is ReviewState.PRIOR_VIEW_INVALIDATED:
            direction = PortfolioImpactDirection.REDUCE_RISK
        elif state in {ReviewState.UNCHANGED, ReviewState.MONITOR}:
            direction = PortfolioImpactDirection.HOLD
        elif current_decision.outcome in {
            RegimeGovernanceOutcome.NO_ACTION,
            RegimeGovernanceOutcome.ESCALATE,
            RegimeGovernanceOutcome.REJECT,
        }:
            direction = PortfolioImpactDirection.REVIEW
        else:
            action = current_decision.recommendation.action
            if action in {
                RecommendationAction.OVERWEIGHT,
                RecommendationAction.ACCUMULATE,
            }:
                direction = PortfolioImpactDirection.INCREASE_RISK
            elif action in {
                RecommendationAction.UNDERWEIGHT,
                RecommendationAction.REDUCE,
                RecommendationAction.AVOID,
            }:
                direction = PortfolioImpactDirection.REDUCE_RISK
            elif state is ReviewState.REVIEW_REQUIRED:
                direction = PortfolioImpactDirection.REBALANCE
            else:
                direction = PortfolioImpactDirection.HOLD
        return PortfolioImpact(
            direction=direction,
            affected_exposures=_REGIME_EXPOSURES[
                current_run.assessment.result.regime
            ],
            explanation=self._impact_explanation(direction),
        )

    @staticmethod
    def _impact_explanation(
        direction: PortfolioImpactDirection,
    ) -> str:
        return {
            PortfolioImpactDirection.HOLD: (
                "Keep the portfolio as it is."
            ),
            PortfolioImpactDirection.REVIEW: (
                "Keep the portfolio steady while the new evidence "
                "is reviewed."
            ),
            PortfolioImpactDirection.INCREASE_RISK: (
                "Review whether the portfolio can take more risk."
            ),
            PortfolioImpactDirection.REDUCE_RISK: (
                "Review whether the portfolio should carry less risk."
            ),
            PortfolioImpactDirection.REBALANCE: (
                "Review the portfolio mix before changing allocations."
            ),
        }[direction]

    @staticmethod
    def _simple_explanation(
        state: ReviewState,
        direction: PortfolioImpactDirection,
    ) -> tuple[str, str]:
        if state is ReviewState.PRIOR_VIEW_INVALIDATED:
            return (
                "Risk review is urgent",
                "Market risk rose enough to challenge the prior view. "
                "Consider reducing risk until the portfolio is reviewed.",
            )
        if state is ReviewState.REVIEW_REQUIRED:
            if direction is PortfolioImpactDirection.INCREASE_RISK:
                explanation = (
                    "The market view became more supportive. Review "
                    "whether the portfolio can take more risk."
                )
            elif direction is PortfolioImpactDirection.REDUCE_RISK:
                explanation = (
                    "The market view weakened. Review whether the "
                    "portfolio should carry less risk."
                )
            elif direction is PortfolioImpactDirection.REVIEW:
                explanation = (
                    "The market view changed, but action is not approved. "
                    "Keep the portfolio steady and review the evidence."
                )
            else:
                explanation = (
                    "The market view changed. Review the portfolio before "
                    "changing allocations."
                )
            return "Portfolio review needed", explanation
        if state is ReviewState.MONITOR:
            return (
                "No portfolio change",
                "Some market evidence moved, but not enough to change "
                "the portfolio.",
            )
        return (
            "Market view unchanged",
            "The market view is unchanged. Keep the portfolio as it is.",
        )


__all__ = [
    "AlertLevel",
    "ChangeCategory",
    "ChangeSeverity",
    "MarketChangeAssessment",
    "MaterialChange",
    "MaterialChangePolicy",
    "PortfolioImpact",
    "PortfolioImpactDirection",
    "RegimeMaterialChangeEngine",
    "ReviewState",
]
