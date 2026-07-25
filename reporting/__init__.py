"""Render immutable analytical and decision results."""

from reporting.capital_intelligence import (
    CapitalIntelligenceComponents,
    CapitalIntelligenceScore,
    CapitalIntelligenceScorePolicy,
    build_capital_intelligence_score,
    capital_intelligence_score_to_dict,
    render_capital_intelligence_score_json,
    render_capital_intelligence_score_markdown,
)
from reporting.decision_card import (
    CIODecisionCard,
    build_cio_decision_card,
    decision_card_to_dict,
    render_decision_card_html,
    render_decision_card_json,
    render_decision_card_markdown,
)
from reporting.decision_replay import (
    DecisionReplay,
    DecisionReplayEvent,
    DecisionReplayPerformance,
    DecisionReplayStep,
    build_decision_replay,
    decision_replay_to_dict,
    render_decision_replay_json,
    render_decision_replay_markdown,
)
from reporting.market_environment import (
    MarketEnvironmentBrief,
    build_market_environment_brief,
    market_environment_brief_to_dict,
    render_market_environment_brief_json,
    render_market_environment_brief_markdown,
)

__all__ = [
    "CapitalIntelligenceComponents",
    "CapitalIntelligenceScore",
    "CapitalIntelligenceScorePolicy",
    "DecisionReplay",
    "DecisionReplayEvent",
    "DecisionReplayPerformance",
    "DecisionReplayStep",
    "MarketEnvironmentBrief",
    "build_capital_intelligence_score",
    "build_cio_decision_card",
    "build_decision_replay",
    "build_market_environment_brief",
    "capital_intelligence_score_to_dict",
    "CIODecisionCard",
    "decision_card_to_dict",
    "decision_replay_to_dict",
    "market_environment_brief_to_dict",
    "render_capital_intelligence_score_json",
    "render_capital_intelligence_score_markdown",
    "render_decision_card_html",
    "render_decision_card_json",
    "render_decision_card_markdown",
    "render_decision_replay_json",
    "render_decision_replay_markdown",
    "render_market_environment_brief_json",
    "render_market_environment_brief_markdown",
]
