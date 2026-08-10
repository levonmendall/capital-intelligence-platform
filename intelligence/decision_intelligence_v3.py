"""Canonical Decision Intelligence v3 read model.

This module assembles the evidence already consumed by the governed CIO cycle into one
read-only, point-in-time packet designed around the portfolio's single economic
objective: maximize long-term compounded dollar value after implementation costs and
within the approved risk/evidence constraints.

The packet does not create candidates, alter specialist conclusions, change CIO
thresholds, size positions, construct a portfolio, or execute. It is a deterministic
explanation and measurement surface over the existing authoritative process.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Mapping

from cio.models import CandidateAssetClass, CIOAction
from intelligence.forward_decision import ForwardDecisionDimension


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text(value: object, *, fallback: str = "unavailable") -> str:
    if value is None:
        return fallback
    normalized = str(value).strip()
    return normalized or fallback


def _finite(value: object, *, fallback: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(fallback)
    normalized = float(value)
    return normalized if isfinite(normalized) else float(fallback)


def _texts(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values.strip(),) if values.strip() else ()
    try:
        resolved = tuple(str(item).strip() for item in values if str(item).strip())
    except TypeError:
        return ()
    return tuple(dict.fromkeys(resolved))


def _enum_value(value: object) -> str:
    return _text(getattr(value, "value", value))


def _target_weight(construction: object | None, symbol: str, current_weight: float) -> float:
    if construction is None:
        return current_weight
    target_weights = getattr(construction, "target_weights", ())
    try:
        mapping = dict(target_weights)
    except (TypeError, ValueError):
        mapping = {}
    return _finite(mapping.get(symbol, current_weight), fallback=current_weight)


def _forward_dimension(context: object, dimension: ForwardDecisionDimension):
    forward = getattr(context, "forward_intelligence", None)
    decision_context = None if forward is None else getattr(forward, "decision_context", None)
    if decision_context is None:
        return None
    for item in tuple(getattr(decision_context, "dimensions", ()) or ()):
        if getattr(item, "dimension", None) is dimension:
            return item
    return None


def _expectations(context: object) -> tuple[str, str, float | None, float | None, tuple[str, ...]]:
    dimension = _forward_dimension(context, ForwardDecisionDimension.EXPECTATIONS)
    if dimension is None:
        return "unavailable", "unavailable", None, None, ()
    market = _text(getattr(dimension, "market_expectation", None))
    internal = _text(getattr(dimension, "internal_expectation", None))
    evidence_ids = _texts(getattr(dimension, "evidence_identifiers", ()))
    confidence = _finite(getattr(dimension, "confidence", 0.0))
    forward = getattr(context, "forward_intelligence", None)
    expected_surprise = None
    priced_in = None
    for owner in (
        forward,
        getattr(forward, "research", None) if forward is not None else None,
        getattr(forward, "predictive", None) if forward is not None else None,
    ):
        expectations = None if owner is None else getattr(owner, "expectations", None)
        if expectations is None:
            continue
        expected_surprise = _finite(getattr(expectations, "expected_surprise", 0.0))
        priced_in = _finite(getattr(expectations, "priced_in_score", 0.0))
        evidence_ids = tuple(
            dict.fromkeys((*evidence_ids, *_texts(getattr(expectations, "evidence_identifiers", ()))))
        )
        break
    return market, internal, expected_surprise, priced_in, evidence_ids + ((f"expectations-confidence:{confidence:.8f}",) if confidence else ())


class DecisionIntelligenceState(str, Enum):
    SELECTED = "selected"
    HELD = "held"
    REDUCED = "reduced"
    EXITED = "exited"
    WATCH = "watch"
    REJECTED = "rejected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class CompoundingObjectiveSnapshot:
    """Dollar-wealth interpretation of the canonical portfolio objective."""

    portfolio_value: float
    cash_weight: float
    cash_expected_return: float
    expected_portfolio_return_after_cost: float
    expected_portfolio_improvement: float
    expected_dollar_value_added: float
    expected_terminal_portfolio_value: float
    objective: str = "maximize_long_term_compounded_dollar_value_after_costs"
    schema_version: str = "compounding-objective-snapshot.v1"

    def __post_init__(self) -> None:
        if self.portfolio_value <= 0.0:
            raise ValueError("portfolio_value must be positive")
        if not 0.0 <= self.cash_weight <= 1.0:
            raise ValueError("cash_weight must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_value": round(self.portfolio_value, 8),
            "cash_weight": round(self.cash_weight, 8),
            "cash_expected_return": round(self.cash_expected_return, 8),
            "expected_portfolio_return_after_cost": round(self.expected_portfolio_return_after_cost, 8),
            "expected_portfolio_improvement": round(self.expected_portfolio_improvement, 8),
            "expected_dollar_value_added": round(self.expected_dollar_value_added, 2),
            "expected_terminal_portfolio_value": round(self.expected_terminal_portfolio_value, 2),
            "objective": self.objective,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class GlobalOpportunityComparison:
    candidate_identifier: str
    symbol: str
    current_weight: float
    proposed_target_weight: float
    candidate_expected_return: float
    cash_expected_return: float
    best_alternative_identifier: str
    best_alternative_expected_return: float
    edge_over_cash: float
    edge_over_best_alternative: float
    marginal_portfolio_improvement: float
    expected_dollar_value_added: float
    changes_portfolio: bool
    schema_version: str = "global-opportunity-comparison.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "symbol": self.symbol,
            "current_weight": round(self.current_weight, 8),
            "proposed_target_weight": round(self.proposed_target_weight, 8),
            "candidate_expected_return": round(self.candidate_expected_return, 8),
            "cash_expected_return": round(self.cash_expected_return, 8),
            "best_alternative_identifier": self.best_alternative_identifier,
            "best_alternative_expected_return": round(self.best_alternative_expected_return, 8),
            "edge_over_cash": round(self.edge_over_cash, 8),
            "edge_over_best_alternative": round(self.edge_over_best_alternative, 8),
            "marginal_portfolio_improvement": round(self.marginal_portfolio_improvement, 8),
            "expected_dollar_value_added": round(self.expected_dollar_value_added, 2),
            "changes_portfolio": self.changes_portfolio,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class DecisionExplanationChain:
    what_changed: tuple[str, ...]
    why_it_matters: tuple[str, ...]
    market_expectation: str
    internal_expectation: str
    expected_surprise: float | None
    priced_in_score: float | None
    bull_case: str
    base_case: str
    bear_case: str
    specialist_disagreements: tuple[str, ...]
    key_risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    monitoring_indicators: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "decision-explanation-chain.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "what_changed": list(self.what_changed),
            "why_it_matters": list(self.why_it_matters),
            "market_expectation": self.market_expectation,
            "internal_expectation": self.internal_expectation,
            "expected_surprise": self.expected_surprise,
            "priced_in_score": self.priced_in_score,
            "bull_case": self.bull_case,
            "base_case": self.base_case,
            "bear_case": self.bear_case,
            "specialist_disagreements": list(self.specialist_disagreements),
            "key_risks": list(self.key_risks),
            "invalidation_conditions": list(self.invalidation_conditions),
            "monitoring_indicators": list(self.monitoring_indicators),
            "evidence_identifiers": list(self.evidence_identifiers),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CandidateDecisionIntelligencePacket:
    identifier: str
    cycle_identifier: str
    candidate_identifier: str
    symbol: str
    name: str
    as_of: datetime
    vehicle_asset_class: CandidateAssetClass
    economic_exposure_class: CandidateAssetClass
    state: DecisionIntelligenceState
    cio_action: str
    cio_confidence: float
    cio_rationale: tuple[str, ...]
    objective: CompoundingObjectiveSnapshot
    opportunity: GlobalOpportunityComparison
    explanation: DecisionExplanationChain
    risk_summary: tuple[str, ...]
    thesis_summary: tuple[str, ...]
    source_lineage: tuple[str, ...]
    investment_authority: bool = False
    construction_authority: bool = False
    execution_authority: bool = False
    schema_version: str = "candidate-decision-intelligence.v3"

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if self.investment_authority or self.construction_authority or self.execution_authority:
            raise ValueError("decision-intelligence packet is read-only and non-authoritative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "cycle_identifier": self.cycle_identifier,
            "candidate_identifier": self.candidate_identifier,
            "symbol": self.symbol,
            "name": self.name,
            "as_of": self.as_of.isoformat(),
            "vehicle_asset_class": self.vehicle_asset_class.value,
            "economic_exposure_class": self.economic_exposure_class.value,
            "state": self.state.value,
            "cio_action": self.cio_action,
            "cio_confidence": round(self.cio_confidence, 8),
            "cio_rationale": list(self.cio_rationale),
            "objective": self.objective.to_dict(),
            "opportunity": self.opportunity.to_dict(),
            "explanation": self.explanation.to_dict(),
            "risk_summary": list(self.risk_summary),
            "thesis_summary": list(self.thesis_summary),
            "source_lineage": list(self.source_lineage),
            "investment_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _decision_state(action: object, *, changed: bool) -> DecisionIntelligenceState:
    if action is CIOAction.BUY or action is CIOAction.INCREASE:
        return DecisionIntelligenceState.SELECTED
    if action is CIOAction.HOLD:
        return DecisionIntelligenceState.HELD
    if action is CIOAction.REDUCE:
        return DecisionIntelligenceState.REDUCED
    if action is CIOAction.EXIT:
        return DecisionIntelligenceState.EXITED
    if action is CIOAction.WATCH:
        return DecisionIntelligenceState.WATCH
    if action is CIOAction.INSUFFICIENT_EVIDENCE:
        return DecisionIntelligenceState.INSUFFICIENT_EVIDENCE
    return DecisionIntelligenceState.NO_CHANGE if not changed else DecisionIntelligenceState.REJECTED


def _scenario_text(candidate: object, name: str) -> str:
    scenario = getattr(candidate, name, None)
    if scenario is None:
        return "unavailable"
    label = _text(getattr(scenario, "label", name))
    expected_return = _finite(getattr(scenario, "total_return", getattr(scenario, "return_impact", 0.0)))
    probability = _finite(getattr(scenario, "probability", 0.0))
    return f"{label}: return {expected_return:+.2%}, probability {probability:.0%}"


def _risk_summary(risk_assessment: object | None, joint_assessment: object | None) -> tuple[str, ...]:
    values: list[str] = []
    for prefix, owner in (("candidate", risk_assessment), ("joint", joint_assessment)):
        if owner is None:
            continue
        for name in (
            "expected_shortfall",
            "stressed_drawdown",
            "liquidity_adjusted_loss",
            "correlation_risk",
            "tail_risk",
            "risk_score",
        ):
            value = getattr(owner, name, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value)):
                values.append(f"{prefix}_{name}={float(value):.6f}")
        values.extend(_texts(getattr(owner, "reasons", ())))
        values.extend(_texts(getattr(owner, "risks", ())))
        values.extend(_texts(getattr(owner, "limitations", ())))
    return tuple(dict.fromkeys(values))


def _thesis_summary(thesis: object | None) -> tuple[str, ...]:
    if thesis is None:
        return ()
    values = []
    for name in ("thesis", "summary", "state"):
        value = getattr(thesis, name, None)
        if value is not None:
            values.append(f"{name}: {_enum_value(value)}")
    values.extend(_texts(getattr(thesis, "must_remain_true", ())))
    values.extend(_texts(getattr(thesis, "invalidation_conditions", ())))
    return tuple(dict.fromkeys(values))


def build_candidate_decision_intelligence_packet(
    *,
    cycle_identifier: str,
    candidate: object,
    specialist_context: object,
    portfolio: object,
    decision: object,
    construction: object | None,
    risk_assessment: object | None = None,
    joint_assessment: object | None = None,
    thesis: object | None = None,
    evaluation_snapshot: object | None = None,
) -> CandidateDecisionIntelligencePacket:
    """Build one deterministic explanation/measurement packet after the CIO cycle."""

    instrument = getattr(candidate, "instrument")
    symbol = _text(getattr(instrument, "symbol"))
    current_weight = _finite(
        getattr(portfolio, "current_weight")(symbol)
        if callable(getattr(portfolio, "current_weight", None))
        else getattr(candidate, "current_portfolio_weight", 0.0)
    )
    target_weight = _target_weight(construction, symbol, current_weight)
    changed = abs(target_weight - current_weight) > 0.000001
    action = getattr(decision, "action", None)
    as_of = _aware(getattr(decision, "as_of", getattr(candidate, "as_of")), field_name="as_of")
    portfolio_value = _finite(getattr(portfolio, "portfolio_value", 0.0))
    cash_return = _finite(getattr(portfolio, "cash_expected_return", 0.0))
    cash_weight = _finite(getattr(portfolio, "cash_weight", 0.0))

    construction_after_cost = _finite(
        getattr(construction, "expected_return_after_cost", 0.0) if construction is not None else 0.0
    )
    construction_improvement = _finite(
        getattr(construction, "expected_return_improvement", 0.0) if construction is not None else 0.0
    )
    expected_dollar_added = portfolio_value * construction_improvement
    objective = CompoundingObjectiveSnapshot(
        portfolio_value=portfolio_value,
        cash_weight=cash_weight,
        cash_expected_return=cash_return,
        expected_portfolio_return_after_cost=construction_after_cost,
        expected_portfolio_improvement=construction_improvement,
        expected_dollar_value_added=expected_dollar_added,
        expected_terminal_portfolio_value=portfolio_value * (1.0 + construction_after_cost),
    )

    candidate_return = _finite(
        getattr(candidate, "net_expected_return", getattr(candidate, "expected_return", 0.0))
    )
    alternative_return = _finite(
        getattr(candidate, "opportunity_cost_return", cash_return), fallback=cash_return
    )
    alternative_identifier = _text(
        getattr(evaluation_snapshot, "best_original_alternative_identifier", None),
        fallback="cash_or_best_governed_alternative",
    )
    opportunity = GlobalOpportunityComparison(
        candidate_identifier=_text(getattr(candidate, "identifier")),
        symbol=symbol,
        current_weight=current_weight,
        proposed_target_weight=target_weight,
        candidate_expected_return=candidate_return,
        cash_expected_return=cash_return,
        best_alternative_identifier=alternative_identifier,
        best_alternative_expected_return=alternative_return,
        edge_over_cash=candidate_return - cash_return,
        edge_over_best_alternative=candidate_return - alternative_return,
        marginal_portfolio_improvement=construction_improvement,
        expected_dollar_value_added=expected_dollar_added,
        changes_portfolio=changed,
    )

    market_expectation, internal_expectation, expected_surprise, priced_in, expectation_ids = _expectations(specialist_context)
    forward = getattr(specialist_context, "forward_intelligence", None)
    decision_context = None if forward is None else getattr(forward, "decision_context", None)
    forward_summaries = []
    forward_ids = []
    if decision_context is not None:
        for dimension in tuple(getattr(decision_context, "dimensions", ()) or ()):
            summary = _text(getattr(dimension, "summary", None))
            availability = _enum_value(getattr(dimension, "availability", "unknown"))
            forward_summaries.append(
                f"{_enum_value(getattr(dimension, 'dimension', 'unknown'))} [{availability}]: {summary}"
            )
            forward_ids.extend(_texts(getattr(dimension, "evidence_identifiers", ())))

    specialist_disagreements = []
    for name in ("limitations", "contradictory_evidence", "risks"):
        specialist_disagreements.extend(_texts(getattr(specialist_context, name, ())))
    forecast = getattr(specialist_context, "forecast", None)
    if forecast is not None:
        specialist_disagreements.extend(_texts(getattr(forecast, "limitations", ())))
        specialist_disagreements.extend(_texts(getattr(forecast, "contradictory_evidence", ())))

    candidate_ids = _texts(getattr(candidate, "evidence_identifiers", ()))
    decision_ids = _texts(getattr(decision, "evidence_identifiers", ()))
    snapshot_ids = _texts(getattr(evaluation_snapshot, "evidence_identifiers", ()))
    source_ids = tuple(
        dict.fromkeys((*candidate_ids, *decision_ids, *snapshot_ids, *forward_ids, *expectation_ids))
    )

    explanation = DecisionExplanationChain(
        what_changed=tuple(
            dict.fromkeys(
                (
                    *_texts(getattr(candidate, "primary_catalysts", ())),
                    *forward_summaries,
                )
            )
        ),
        why_it_matters=tuple(
            dict.fromkeys(
                (
                    *_texts(getattr(candidate, "supporting_evidence", ())),
                    *_texts(getattr(decision, "rationale", ())),
                )
            )
        ),
        market_expectation=market_expectation,
        internal_expectation=internal_expectation,
        expected_surprise=expected_surprise,
        priced_in_score=priced_in,
        bull_case=_scenario_text(candidate, "bull_case"),
        base_case=_scenario_text(candidate, "base_case"),
        bear_case=_scenario_text(candidate, "bear_case"),
        specialist_disagreements=tuple(dict.fromkeys(specialist_disagreements)),
        key_risks=_texts(getattr(candidate, "key_risks", ())),
        invalidation_conditions=_texts(getattr(candidate, "thesis_invalidation_conditions", getattr(candidate, "invalidation_conditions", ()))),
        monitoring_indicators=_texts(getattr(candidate, "monitoring_indicators", ())),
        evidence_identifiers=source_ids,
    )

    vehicle_class = getattr(instrument, "asset_class")
    if not isinstance(vehicle_class, CandidateAssetClass):
        raise TypeError("candidate vehicle asset class must be CandidateAssetClass")
    economic_class = getattr(instrument, "economic_exposure_class", None) or vehicle_class
    if not isinstance(economic_class, CandidateAssetClass):
        raise TypeError("candidate economic exposure class must be CandidateAssetClass")

    rationale = _texts(getattr(decision, "rationale", ()))
    if not rationale:
        rationale = (_text(getattr(decision, "reason", None)),)
    confidence = _finite(getattr(decision, "confidence", getattr(decision, "final_confidence", 0.0)))
    candidate_identifier = _text(getattr(candidate, "identifier"))
    return CandidateDecisionIntelligencePacket(
        identifier=f"decision-intelligence-v3:{cycle_identifier}:{candidate_identifier}",
        cycle_identifier=cycle_identifier,
        candidate_identifier=candidate_identifier,
        symbol=symbol,
        name=_text(getattr(instrument, "name", symbol)),
        as_of=as_of,
        vehicle_asset_class=vehicle_class,
        economic_exposure_class=economic_class,
        state=_decision_state(action, changed=changed),
        cio_action=_enum_value(action),
        cio_confidence=max(0.0, min(1.0, confidence)),
        cio_rationale=rationale,
        objective=objective,
        opportunity=opportunity,
        explanation=explanation,
        risk_summary=_risk_summary(risk_assessment, joint_assessment),
        thesis_summary=_thesis_summary(thesis),
        source_lineage=source_ids,
    )


__all__ = [
    "CandidateDecisionIntelligencePacket",
    "CompoundingObjectiveSnapshot",
    "DecisionExplanationChain",
    "DecisionIntelligenceState",
    "GlobalOpportunityComparison",
    "build_candidate_decision_intelligence_packet",
]
