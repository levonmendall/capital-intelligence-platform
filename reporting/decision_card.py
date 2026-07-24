"""Mobile-first CIO decision card built from immutable domain results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

from committee.regime_governance import (
    RegimeCommitteeDecision,
    RegimeGovernanceOutcome,
)
from intelligence.recommendation import RecommendationAction
from intelligence.regime_pipeline import InstitutionalRegimeRun
from monitoring import (
    AlertLevel,
    MarketChangeAssessment,
    PortfolioImpactDirection,
)


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


def _text_tuple(
    value: object,
    *,
    field_name: str,
    maximum: int = 3,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name)
        for item in value
    )
    if len(normalized) > maximum:
        raise ValueError(
            f"{field_name} cannot contain more than {maximum} items"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class CIODecisionCard:
    """One concise, portfolio-oriented view of a governed decision."""

    identifier: str
    as_of: datetime
    headline: str
    decision: str
    why_now: str
    regime: str
    evidence_confidence: float
    data_status: str
    committee_outcome: str
    portfolio_direction: PortfolioImpactDirection
    portfolio_explanation: str
    affected_exposures: tuple[str, ...]
    key_evidence: tuple[str, ...]
    key_risks: tuple[str, ...]
    watch_conditions: tuple[str, ...]
    alert_level: AlertLevel = AlertLevel.SILENT
    review_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "headline",
            "decision",
            "why_now",
            "regime",
            "data_status",
            "committee_outcome",
            "portfolio_explanation",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        _aware_datetime(self.as_of, field_name="as_of")
        if (
            isinstance(self.evidence_confidence, bool)
            or not isinstance(
                self.evidence_confidence,
                (int, float),
            )
        ):
            raise TypeError("evidence_confidence must be numeric")
        confidence = float(self.evidence_confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "evidence_confidence must be between 0.0 and 1.0"
            )
        object.__setattr__(
            self,
            "evidence_confidence",
            round(confidence, 4),
        )
        if not isinstance(
            self.portfolio_direction,
            PortfolioImpactDirection,
        ):
            raise TypeError(
                "portfolio_direction must be a "
                "PortfolioImpactDirection"
            )
        if not isinstance(self.alert_level, AlertLevel):
            raise TypeError("alert_level must be an AlertLevel")
        for field_name in (
            "affected_exposures",
            "key_evidence",
            "key_risks",
            "watch_conditions",
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if self.review_at is not None:
            _aware_datetime(self.review_at, field_name="review_at")

    @property
    def should_alert(self) -> bool:
        return self.alert_level is not AlertLevel.SILENT


_COMMITTEE_LABELS = {
    RegimeGovernanceOutcome.APPROVE: "Approved",
    RegimeGovernanceOutcome.MODIFY: "Approved with changes",
    RegimeGovernanceOutcome.REJECT: "Rejected",
    RegimeGovernanceOutcome.ESCALATE: "Needs committee review",
    RegimeGovernanceOutcome.NO_ACTION: "No action",
}


def build_cio_decision_card(
    run: InstitutionalRegimeRun,
    decision: RegimeCommitteeDecision,
    *,
    change: MarketChangeAssessment | None = None,
) -> CIODecisionCard:
    """Compress existing results without recalculating their conclusions."""

    if not isinstance(run, InstitutionalRegimeRun):
        raise TypeError("run must be an InstitutionalRegimeRun")
    if not isinstance(decision, RegimeCommitteeDecision):
        raise TypeError(
            "decision must be a RegimeCommitteeDecision"
        )
    timestamp = run.as_of.isoformat()
    if timestamp not in decision.recommendation.identifier:
        raise ValueError("decision must reference run")
    if change is not None:
        if not isinstance(change, MarketChangeAssessment):
            raise TypeError(
                "change must be a MarketChangeAssessment"
            )
        if change.current_as_of != run.as_of:
            raise ValueError(
                "change must use run as its current analysis"
            )

    confidence = run.assessment.confidence
    data_status = _data_status(run)
    committee_outcome = _COMMITTEE_LABELS[decision.outcome]
    portfolio_direction = _portfolio_direction(decision, change)
    portfolio_explanation = _portfolio_explanation(
        portfolio_direction,
        decision,
        change,
    )
    affected_exposures = _affected_exposures(decision, change)
    review_at = (
        decision.no_action.review_at
        if decision.no_action is not None
        else None
    )
    return CIODecisionCard(
        identifier=f"cio-decision-card:{timestamp}",
        as_of=run.as_of,
        headline=_headline(decision, change),
        decision=_decision_summary(decision),
        why_now=_why_now(run, decision, change),
        regime=run.assessment.result.regime.value,
        evidence_confidence=confidence,
        data_status=data_status,
        committee_outcome=committee_outcome,
        portfolio_direction=portfolio_direction,
        portfolio_explanation=portfolio_explanation,
        affected_exposures=affected_exposures,
        key_evidence=tuple(
            decision.recommendation.supporting_evidence[:3]
        ),
        key_risks=tuple(decision.recommendation.risks[:3]),
        watch_conditions=_watch_conditions(decision),
        alert_level=(
            change.alert_level
            if change is not None
            else AlertLevel.SILENT
        ),
        review_at=review_at,
    )


def _data_status(run: InstitutionalRegimeRun) -> str:
    evidence = run.assessment.evidence
    if (
        evidence.data_coverage == 1.0
        and evidence.quality_score >= 0.90
    ):
        return "Complete"
    if (
        evidence.data_coverage >= 0.80
        and evidence.quality_score >= 0.75
    ):
        return "Usable with limits"
    return "Limited"


def _headline(
    decision: RegimeCommitteeDecision,
    change: MarketChangeAssessment | None,
) -> str:
    if change is not None:
        return change.headline
    if decision.outcome is RegimeGovernanceOutcome.NO_ACTION:
        return "No portfolio change"
    if decision.outcome is RegimeGovernanceOutcome.ESCALATE:
        return "Portfolio review needed"
    if decision.outcome is RegimeGovernanceOutcome.REJECT:
        return "Proposed change rejected"
    if decision.outcome is RegimeGovernanceOutcome.MODIFY:
        return "Changes required before action"
    return "Portfolio action approved"


def _decision_summary(decision: RegimeCommitteeDecision) -> str:
    if decision.outcome is RegimeGovernanceOutcome.NO_ACTION:
        return "Keep the portfolio unchanged."
    if decision.outcome is RegimeGovernanceOutcome.ESCALATE:
        return (
            "Keep the portfolio unchanged while the decision is reviewed."
        )
    if decision.outcome is RegimeGovernanceOutcome.REJECT:
        return "Do not make the proposed portfolio change."
    if decision.outcome is RegimeGovernanceOutcome.MODIFY:
        return "Review the required changes before acting."
    recommendation = decision.recommendation
    target = recommendation.target.replace("_", " ")
    return {
        RecommendationAction.OVERWEIGHT: (
            f"Consider holding more {target}."
        ),
        RecommendationAction.ACCUMULATE: (
            f"Consider adding {target} gradually."
        ),
        RecommendationAction.UNDERWEIGHT: (
            f"Consider holding less {target}."
        ),
        RecommendationAction.REDUCE: (
            f"Consider reducing {target}."
        ),
        RecommendationAction.AVOID: f"Avoid adding {target}.",
        RecommendationAction.NEUTRAL: (
            f"Keep {target} near its current weight."
        ),
    }[recommendation.action]


def _why_now(
    run: InstitutionalRegimeRun,
    decision: RegimeCommitteeDecision,
    change: MarketChangeAssessment | None,
) -> str:
    if change is not None:
        return change.explanation
    if decision.outcome is RegimeGovernanceOutcome.NO_ACTION:
        return (
            "The evidence is not strong enough to support a portfolio "
            "change."
        )
    if decision.outcome is RegimeGovernanceOutcome.ESCALATE:
        return (
            "The evidence needs further committee review before action."
        )
    return (
        f"{run.assessment.result.regime.value} conditions support this "
        f"view with {run.assessment.confidence:.0%} evidence confidence."
    )


def _portfolio_direction(
    decision: RegimeCommitteeDecision,
    change: MarketChangeAssessment | None,
) -> PortfolioImpactDirection:
    if change is not None:
        return change.portfolio_impact.direction
    if decision.outcome in {
        RegimeGovernanceOutcome.NO_ACTION,
        RegimeGovernanceOutcome.REJECT,
    }:
        return PortfolioImpactDirection.HOLD
    if decision.outcome in {
        RegimeGovernanceOutcome.ESCALATE,
        RegimeGovernanceOutcome.MODIFY,
    }:
        return PortfolioImpactDirection.REVIEW
    action = decision.recommendation.action
    if action in {
        RecommendationAction.OVERWEIGHT,
        RecommendationAction.ACCUMULATE,
    }:
        return PortfolioImpactDirection.INCREASE_RISK
    if action in {
        RecommendationAction.UNDERWEIGHT,
        RecommendationAction.REDUCE,
        RecommendationAction.AVOID,
    }:
        return PortfolioImpactDirection.REDUCE_RISK
    return PortfolioImpactDirection.HOLD


def _portfolio_explanation(
    direction: PortfolioImpactDirection,
    decision: RegimeCommitteeDecision,
    change: MarketChangeAssessment | None,
) -> str:
    if change is not None:
        return change.portfolio_impact.explanation
    if direction is PortfolioImpactDirection.HOLD:
        return "Keep the portfolio as it is."
    if direction is PortfolioImpactDirection.REVIEW:
        return "Keep the portfolio steady while the decision is reviewed."
    if direction is PortfolioImpactDirection.INCREASE_RISK:
        return "Review whether the portfolio can take more risk."
    if direction is PortfolioImpactDirection.REDUCE_RISK:
        return "Review whether the portfolio should carry less risk."
    return "Review the portfolio mix before changing allocations."


def _affected_exposures(
    decision: RegimeCommitteeDecision,
    change: MarketChangeAssessment | None,
) -> tuple[str, ...]:
    if change is not None:
        exposures = change.portfolio_impact.affected_exposures
        crypto = "crypto risk budget"
        if len(exposures) > 3 and crypto in exposures:
            return (*exposures[:2], crypto)
        return exposures[:3]
    return (
        decision.recommendation.target.replace("_", " "),
    )


def _watch_conditions(
    decision: RegimeCommitteeDecision,
) -> tuple[str, ...]:
    if decision.no_action is not None:
        return tuple(decision.no_action.action_triggers[:3])
    return tuple(
        decision.recommendation.invalidation_conditions[:3]
    )


def decision_card_to_dict(card: CIODecisionCard) -> dict[str, Any]:
    """Return a stable public representation of one decision card."""

    if not isinstance(card, CIODecisionCard):
        raise TypeError("card must be a CIODecisionCard")
    return {
        "schema_version": "cio-decision-card.v1",
        "identifier": card.identifier,
        "as_of": card.as_of.isoformat(),
        "headline": card.headline,
        "decision": card.decision,
        "why_now": card.why_now,
        "regime": card.regime,
        "evidence_confidence": card.evidence_confidence,
        "data_status": card.data_status,
        "committee_outcome": card.committee_outcome,
        "portfolio": {
            "direction": card.portfolio_direction.value,
            "explanation": card.portfolio_explanation,
            "affected_exposures": list(card.affected_exposures),
        },
        "key_evidence": list(card.key_evidence),
        "key_risks": list(card.key_risks),
        "watch_conditions": list(card.watch_conditions),
        "alert_level": card.alert_level.value,
        "should_alert": card.should_alert,
        "review_at": (
            card.review_at.isoformat()
            if card.review_at is not None
            else None
        ),
    }


def render_decision_card_json(
    card: CIODecisionCard,
    *,
    indent: int | None = 2,
) -> str:
    """Render deterministic JSON for APIs and stored artifacts."""

    if indent is not None and (
        isinstance(indent, bool)
        or not isinstance(indent, int)
        or indent < 0
    ):
        raise ValueError("indent must be a non-negative int or None")
    return json.dumps(
        decision_card_to_dict(card),
        sort_keys=True,
        indent=indent,
        allow_nan=False,
    )


def render_decision_card_markdown(card: CIODecisionCard) -> str:
    """Render a compact card with progressively disclosed detail."""

    if not isinstance(card, CIODecisionCard):
        raise TypeError("card must be a CIODecisionCard")
    lines = [
        f"# {card.headline}",
        "",
        card.decision,
        "",
        f"**Why now:** {card.why_now}",
        "",
        (
            f"**Portfolio:** {card.portfolio_explanation} "
            f"({', '.join(card.affected_exposures)})"
        ),
        "",
        (
            f"**Regime:** {card.regime} · "
            f"**Confidence:** {card.evidence_confidence:.0%} · "
            f"**Data:** {card.data_status} · "
            f"**Committee:** {card.committee_outcome}"
        ),
        "",
        "<details>",
        "<summary>Evidence, risks, and review conditions</summary>",
        "",
        "## Evidence",
        "",
        *[f"- {item}" for item in card.key_evidence],
        "",
        "## Risks",
        "",
        *[f"- {item}" for item in card.key_risks],
        "",
        "## Review when",
        "",
        *[f"- {item}" for item in card.watch_conditions],
    ]
    if card.review_at is not None:
        lines.extend(
            (
                "",
                f"Next scheduled review: {card.review_at.isoformat()}",
            )
        )
    lines.extend(("", "</details>", ""))
    return "\n".join(lines)


def render_decision_card_html(card: CIODecisionCard) -> str:
    """Render accessible, responsive HTML with no script dependency."""

    if not isinstance(card, CIODecisionCard):
        raise TypeError("card must be a CIODecisionCard")

    def items(values: tuple[str, ...]) -> str:
        return "".join(f"<li>{escape(value)}</li>" for value in values)

    exposures = ", ".join(card.affected_exposures)
    review = (
        ""
        if card.review_at is None
        else (
            "<p class=\"review\"><strong>Next review:</strong> "
            f"{escape(card.review_at.isoformat())}</p>"
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(card.headline)} · Capital Intelligence</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --surface: #ffffff;
      --ink: #172033;
      --muted: #5d687a;
      --line: #d9deea;
      --accent: #315efb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 20px;
      background: #f3f5f9;
      color: var(--ink);
    }}
    main {{
      width: min(100%, 680px);
      margin: 0 auto;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: var(--surface);
      box-shadow: 0 12px 32px rgba(20, 32, 60, 0.08);
    }}
    .eyebrow, .meta {{ color: var(--muted); }}
    .eyebrow {{
      margin: 0 0 8px;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 0; font-size: clamp(1.65rem, 7vw, 2.25rem); }}
    .decision {{ margin: 18px 0 8px; font-size: 1.2rem; font-weight: 700; }}
    .why {{ margin: 0 0 20px; color: var(--muted); line-height: 1.5; }}
    .impact {{
      padding: 16px;
      border-left: 4px solid var(--accent);
      border-radius: 10px;
      background: color-mix(in srgb, var(--accent) 8%, var(--surface));
    }}
    .impact p {{ margin: 0 0 6px; }}
    .impact small {{ color: var(--muted); }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 20px 0;
      font-size: 0.9rem;
    }}
    .meta span {{
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
    }}
    details {{ border-top: 1px solid var(--line); padding-top: 16px; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    h2 {{ margin: 20px 0 8px; font-size: 1rem; }}
    ul {{ margin: 0; padding-left: 20px; color: var(--muted); }}
    li + li {{ margin-top: 8px; }}
    .review {{ color: var(--muted); }}
    @media (max-width: 430px) {{
      body {{ padding: 10px; }}
      main {{ padding: 20px; border-radius: 16px; }}
      .meta {{ grid-template-columns: 1fr; }}
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --surface: #111723;
        --ink: #f4f7ff;
        --muted: #aab4c7;
        --line: #30394b;
        --accent: #86a3ff;
      }}
      body {{ background: #090d15; }}
    }}
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">CIO decision · {escape(card.as_of.isoformat())}</p>
    <h1>{escape(card.headline)}</h1>
    <p class="decision">{escape(card.decision)}</p>
    <p class="why">{escape(card.why_now)}</p>
    <section class="impact" aria-label="Portfolio impact">
      <p><strong>{escape(card.portfolio_explanation)}</strong></p>
      <small>Affects: {escape(exposures)}</small>
    </section>
    <section class="meta" aria-label="Decision summary">
      <span><strong>Regime</strong><br>{escape(card.regime)}</span>
      <span><strong>Confidence</strong><br>{card.evidence_confidence:.0%}</span>
      <span><strong>Data</strong><br>{escape(card.data_status)}</span>
      <span><strong>Committee</strong><br>{escape(card.committee_outcome)}</span>
    </section>
    <details>
      <summary>Evidence, risks, and review conditions</summary>
      <h2>Evidence</h2><ul>{items(card.key_evidence)}</ul>
      <h2>Risks</h2><ul>{items(card.key_risks)}</ul>
      <h2>Review when</h2><ul>{items(card.watch_conditions)}</ul>
      {review}
    </details>
  </main>
</body>
</html>
"""


__all__ = [
    "CIODecisionCard",
    "build_cio_decision_card",
    "decision_card_to_dict",
    "render_decision_card_html",
    "render_decision_card_json",
    "render_decision_card_markdown",
]
