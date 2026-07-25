"""Concise daily market-environment brief for the primary product surface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from committee.regime_governance import RegimeCommitteeDecision
from intelligence.regime_pipeline import InstitutionalRegimeRun
from monitoring import AlertLevel, MarketChangeAssessment, PortfolioImpactDirection
from reporting.decision_card import build_cio_decision_card


@dataclass(frozen=True, slots=True)
class MarketEnvironmentBrief:
    """Simple, portfolio-oriented answer to “what is happening today?”"""

    as_of: datetime
    regime: str
    headline: str
    summary: str
    portfolio_direction: PortfolioImpactDirection
    portfolio_impact: str
    affected_exposures: tuple[str, ...]
    confidence: float
    data_status: str
    changed_materially: bool
    alert_level: AlertLevel
    review_conditions: tuple[str, ...]

    @property
    def should_alert(self) -> bool:
        return self.alert_level is not AlertLevel.SILENT


def build_market_environment_brief(
    run: InstitutionalRegimeRun,
    decision: RegimeCommitteeDecision,
    *,
    change: MarketChangeAssessment | None = None,
) -> MarketEnvironmentBrief:
    """Build a read-only brief without recalculating analytical conclusions."""

    card = build_cio_decision_card(run, decision, change=change)
    changed_materially = bool(change and change.should_alert)

    if change is None:
        headline = f"{card.regime} conditions remain the working view"
        summary = card.why_now
    elif change.should_alert:
        headline = change.headline
        summary = change.explanation
    else:
        headline = f"No meaningful change in {card.regime.lower()} conditions"
        summary = (
            "The intelligence engine found no portfolio-relevant change. "
            "The current positioning view remains in place."
        )

    return MarketEnvironmentBrief(
        as_of=card.as_of,
        regime=card.regime,
        headline=headline,
        summary=summary,
        portfolio_direction=card.portfolio_direction,
        portfolio_impact=card.portfolio_explanation,
        affected_exposures=card.affected_exposures,
        confidence=card.evidence_confidence,
        data_status=card.data_status,
        changed_materially=changed_materially,
        alert_level=card.alert_level,
        review_conditions=card.watch_conditions,
    )


def market_environment_brief_to_dict(
    brief: MarketEnvironmentBrief,
) -> dict[str, object]:
    """Return the stable API representation for the environment screen."""

    if not isinstance(brief, MarketEnvironmentBrief):
        raise TypeError("brief must be a MarketEnvironmentBrief")
    return {
        "schema_version": "market-environment-brief.v1",
        "as_of": brief.as_of.isoformat(),
        "regime": brief.regime,
        "headline": brief.headline,
        "summary": brief.summary,
        "portfolio": {
            "direction": brief.portfolio_direction.value,
            "impact": brief.portfolio_impact,
            "affected_exposures": list(brief.affected_exposures),
        },
        "confidence": brief.confidence,
        "data_status": brief.data_status,
        "changed_materially": brief.changed_materially,
        "alert_level": brief.alert_level.value,
        "should_alert": brief.should_alert,
        "review_conditions": list(brief.review_conditions),
    }


def render_market_environment_brief_json(
    brief: MarketEnvironmentBrief,
) -> str:
    """Render deterministic JSON for API or client consumption."""

    return json.dumps(
        market_environment_brief_to_dict(brief),
        indent=2,
        sort_keys=True,
    )


def render_market_environment_brief_markdown(
    brief: MarketEnvironmentBrief,
) -> str:
    """Render the compact daily environment surface."""

    exposures = ", ".join(brief.affected_exposures) or "none"
    return "\n".join(
        (
            f"# {brief.headline}",
            "",
            brief.summary,
            "",
            f"**Environment:** {brief.regime}",
            f"**Portfolio:** {brief.portfolio_impact}",
            f"**Affected exposures:** {exposures}",
            f"**Confidence:** {brief.confidence:.0%}",
            f"**Data:** {brief.data_status}",
            f"**Alert:** {'Yes' if brief.should_alert else 'No'}",
        )
    )


__all__ = [
    "MarketEnvironmentBrief",
    "build_market_environment_brief",
    "market_environment_brief_to_dict",
    "render_market_environment_brief_json",
    "render_market_environment_brief_markdown",
]
