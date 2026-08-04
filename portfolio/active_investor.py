"""Governed active-investor loop for expression, lifecycle, reaction, and accountability.

This module completes the bridge between portfolio posture and ongoing portfolio
management.  It may rank certified candidates as expressions of a governed view,
propose position-lifecycle states, declare incremental reassessment dependencies, and
measure prospective compounding opportunity cost.  It cannot create an instrument,
issue a CIO action, construct a portfolio, execute an order, alter policy, or authorize
real money.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio.models import CIOAction, CandidateAssetClass, ThesisState
from portfolio.compounding_allocation import (
    CandidateAllocationDirective,
    CompoundingPortfolioAlternativeSet,
    PortfolioPosture,
    PortfolioRegime,
    PortfolioSleeve,
)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(
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
    return round(normalized, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _finite(value, field_name=field_name, minimum=0.0, maximum=1.0)


def _bounded(value: object, *, field_name: str) -> float:
    return _finite(value, field_name=field_name, minimum=-1.0, maximum=1.0)


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(high, float(value))), 8)


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _signal_values(context: object | None) -> tuple[float, float, float]:
    bundle = getattr(context, "forward_intelligence", None)
    signals = tuple(getattr(bundle, "signals", ()) or ())
    flow_impact = 0.0
    expectations_impact = 0.0
    confidence_values: list[float] = []
    for signal in signals:
        identifier = str(getattr(signal, "identifier", "")).lower()
        name = str(getattr(signal, "name", "")).lower()
        impact = float(getattr(signal, "expected_return_impact", 0.0))
        confidence = float(getattr(signal, "confidence", 0.0))
        if "capital-flow" in identifier or "capital flow" in name or "flow proxy" in name:
            flow_impact += impact
            confidence_values.append(confidence)
        if "market-expectations" in identifier or "expectations gap" in name:
            expectations_impact += impact
            confidence_values.append(confidence)
    confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values
        else 0.0
    )
    return (
        _clip(flow_impact, -0.15, 0.15),
        _clip(expectations_impact, -0.15, 0.15),
        _clip(confidence),
    )


class InvestmentViewKind(str, Enum):
    PRODUCTIVE_RISK = "productive_risk"
    DEFENSIVE_DURATION = "defensive_duration"
    DOLLAR_STRENGTH = "dollar_strength"
    INFLATION_PROTECTION = "inflation_protection"
    DIVERSIFICATION = "diversification"
    LIQUIDITY_RESERVE = "liquidity_reserve"


@dataclass(frozen=True, slots=True)
class InvestmentView:
    identifier: str
    as_of: datetime
    kind: InvestmentViewKind
    direction: float
    confidence: float
    transition_probability: float
    preferred_asset_classes: tuple[CandidateAssetClass, ...]
    rationale: str
    catalysts: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    model_version: str = "investment-view.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.kind, InvestmentViewKind):
            raise TypeError("kind must be InvestmentViewKind")
        object.__setattr__(self, "direction", _bounded(self.direction, field_name="direction"))
        object.__setattr__(self, "confidence", _ratio(self.confidence, field_name="confidence"))
        object.__setattr__(
            self,
            "transition_probability",
            _ratio(self.transition_probability, field_name="transition_probability"),
        )
        if not isinstance(self.preferred_asset_classes, tuple) or not all(
            isinstance(item, CandidateAssetClass) for item in self.preferred_asset_classes
        ):
            raise TypeError("preferred_asset_classes must contain CandidateAssetClass values")
        if not self.preferred_asset_classes:
            raise ValueError("a view requires at least one preferred asset class")
        if len(self.preferred_asset_classes) != len(set(self.preferred_asset_classes)):
            raise ValueError("preferred_asset_classes cannot contain duplicates")
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))
        for field_name, minimum in (
            ("catalysts", 1),
            ("invalidation_conditions", 1),
            ("evidence_identifiers", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        object.__setattr__(self, "model_version", _text(self.model_version, field_name="model_version"))

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "kind": self.kind.value,
            "direction": self.direction,
            "confidence": self.confidence,
            "transition_probability": self.transition_probability,
            "preferred_asset_classes": [item.value for item in self.preferred_asset_classes],
            "rationale": self.rationale,
            "catalysts": list(self.catalysts),
            "invalidation_conditions": list(self.invalidation_conditions),
            "evidence_identifiers": list(self.evidence_identifiers),
            "model_version": self.model_version,
            "investment_authority": False,
        }


@dataclass(frozen=True, slots=True)
class InvestableExpression:
    view_identifier: str
    candidate_identifier: str
    symbol: str
    directness: float
    posture_alignment: float
    expected_edge_score: float
    flow_confirmation: float
    expectations_confirmation: float
    liquidity: float
    cost_efficiency: float
    diversification_value: float
    expression_score: float
    rank: int
    rationale: str
    limitations: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("view_identifier", "candidate_identifier", "symbol", "rationale"):
            value = _text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(self, field_name, value.upper() if field_name == "symbol" else value)
        for field_name in (
            "directness",
            "expected_edge_score",
            "flow_confirmation",
            "expectations_confirmation",
            "liquidity",
            "cost_efficiency",
            "diversification_value",
            "expression_score",
        ):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        object.__setattr__(
            self,
            "posture_alignment",
            _bounded(self.posture_alignment, field_name="posture_alignment"),
        )
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        object.__setattr__(self, "limitations", _texts(self.limitations, field_name="limitations", minimum=1))
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["limitations"] = list(self.limitations)
        payload["evidence_identifiers"] = list(self.evidence_identifiers)
        payload["candidate_creation_authority"] = False
        payload["investment_authority"] = False
        return payload


@dataclass(frozen=True, slots=True)
class ViewExpressionSet:
    identifier: str
    as_of: datetime
    posture_identifier: str
    views: tuple[InvestmentView, ...]
    expressions: tuple[InvestableExpression, ...]
    uncovered_views: tuple[str, ...]
    model_version: str = "view-to-expression.v1-certified-universe"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "posture_identifier",
            _text(self.posture_identifier, field_name="posture_identifier"),
        )
        if not isinstance(self.views, tuple) or not all(isinstance(item, InvestmentView) for item in self.views):
            raise TypeError("views must contain InvestmentView values")
        if not self.views:
            raise ValueError("at least one investment view is required")
        if not isinstance(self.expressions, tuple) or not all(
            isinstance(item, InvestableExpression) for item in self.expressions
        ):
            raise TypeError("expressions must contain InvestableExpression values")
        keys = tuple((item.view_identifier, item.candidate_identifier) for item in self.expressions)
        if len(keys) != len(set(keys)):
            raise ValueError("view/candidate expressions must be unique")
        object.__setattr__(self, "uncovered_views", _texts(self.uncovered_views, field_name="uncovered_views"))
        object.__setattr__(self, "model_version", _text(self.model_version, field_name="model_version"))

    def best_for_candidate(self, candidate_identifier: str) -> InvestableExpression | None:
        matches = tuple(
            item for item in self.expressions if item.candidate_identifier == candidate_identifier
        )
        return max(matches, key=lambda item: item.expression_score, default=None)

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "posture_identifier": self.posture_identifier,
            "views": [item.to_dict() for item in self.views],
            "expressions": [item.to_dict() for item in self.expressions],
            "uncovered_views": list(self.uncovered_views),
            "model_version": self.model_version,
            "candidate_creation_authority": False,
            "cio_authority": False,
        }


class ViewToExpressionEngine:
    version = "view-to-expression-engine.v1"

    _PRODUCTIVE = (
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.US_ETF,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.REAL_ESTATE,
        CandidateAssetClass.CRYPTO,
    )
    _DEFENSIVE = (
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.CASH_EQUIVALENT,
        CandidateAssetClass.US_ETF,
    )
    _DOLLAR = (
        CandidateAssetClass.FX,
        CandidateAssetClass.CASH_EQUIVALENT,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.US_ETF,
    )
    _INFLATION = (
        CandidateAssetClass.COMMODITY,
        CandidateAssetClass.REAL_ESTATE,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.US_ETF,
    )
    _DIVERSIFIERS = (
        CandidateAssetClass.COMMODITY,
        CandidateAssetClass.REAL_ESTATE,
        CandidateAssetClass.ALTERNATIVE,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.US_ETF,
    )

    def build(
        self,
        *,
        posture: PortfolioPosture,
        candidates: Sequence[object],
        specialist_contexts: Sequence[object],
        directives: Sequence[CandidateAllocationDirective],
    ) -> ViewExpressionSet:
        if not isinstance(posture, PortfolioPosture):
            raise TypeError("posture must be PortfolioPosture")
        candidate_values = tuple(candidates)
        contexts = {
            str(getattr(item, "candidate_identifier")): item
            for item in specialist_contexts
        }
        directive_by_candidate = {
            item.candidate_identifier: item for item in directives
        }
        views = self._views(posture)
        expression_rows: list[tuple[InvestmentView, object, dict[str, float], tuple[str, ...]]] = []
        for view in views:
            for candidate in candidate_values:
                instrument = getattr(candidate, "instrument")
                asset_class = getattr(instrument, "asset_class")
                if asset_class not in view.preferred_asset_classes:
                    continue
                candidate_identifier = str(getattr(candidate, "identifier"))
                directive = directive_by_candidate.get(candidate_identifier)
                context = contexts.get(candidate_identifier)
                flow_impact, expectations_impact, signal_confidence = _signal_values(context)
                directness = self._directness(view, candidate)
                alignment = (
                    float(directive.posture_alignment) if directive is not None else 0.0
                )
                edge = float(getattr(candidate, "net_expected_return", 0.0)) - float(
                    getattr(candidate, "opportunity_cost_return", 0.0)
                )
                expected_edge_score = _clip(0.50 + edge / 0.20)
                flow_confirmation = _clip(0.50 + flow_impact / 0.20)
                expectations_confirmation = _clip(0.50 + expectations_impact / 0.20)
                liquidity = _clip(float(getattr(candidate, "liquidity_score", 0.0)))
                total_cost_bps = float(getattr(candidate, "transaction_cost_bps", 0.0)) + float(
                    getattr(candidate, "slippage_bps", 0.0)
                )
                cost_efficiency = _clip(1.0 - total_cost_bps / 100.0)
                current_weight = float(getattr(candidate, "current_portfolio_weight", 0.0))
                diversification = _clip(1.0 - min(1.0, current_weight * 5.0))
                alignment_score = _clip(0.50 + alignment / 2.0)
                score = _clip(
                    0.24 * directness
                    + 0.18 * alignment_score
                    + 0.20 * expected_edge_score
                    + 0.10 * flow_confirmation
                    + 0.10 * expectations_confirmation
                    + 0.07 * liquidity
                    + 0.05 * cost_efficiency
                    + 0.04 * diversification
                    + 0.02 * signal_confidence
                )
                limitations = [
                    "Expression ranking does not authorize capital and remains subject to the complete six-specialist, CIO, construction, and paper-execution path"
                ]
                if signal_confidence <= 0.0:
                    limitations.append("No structured predictive flow or expectations signal was available")
                if directness < 0.60:
                    limitations.append("The instrument is an indirect expression of the investment view")
                evidence_ids = tuple(
                    dict.fromkeys(
                        (
                            *tuple(getattr(candidate, "evidence_identifiers", ()) or ()),
                            posture.identifier,
                            view.identifier,
                        )
                    )
                )
                expression_rows.append(
                    (
                        view,
                        candidate,
                        {
                            "directness": directness,
                            "posture_alignment": alignment,
                            "expected_edge_score": expected_edge_score,
                            "flow_confirmation": flow_confirmation,
                            "expectations_confirmation": expectations_confirmation,
                            "liquidity": liquidity,
                            "cost_efficiency": cost_efficiency,
                            "diversification_value": diversification,
                            "expression_score": score,
                        },
                        tuple(dict.fromkeys(limitations)),
                    )
                )
        expressions: list[InvestableExpression] = []
        for view in views:
            rows = [item for item in expression_rows if item[0].identifier == view.identifier]
            rows.sort(
                key=lambda item: (
                    -item[2]["expression_score"],
                    str(getattr(getattr(item[1], "instrument"), "symbol")),
                )
            )
            for rank, (_view, candidate, values, limitations) in enumerate(rows, start=1):
                instrument = getattr(candidate, "instrument")
                expressions.append(
                    InvestableExpression(
                        view_identifier=view.identifier,
                        candidate_identifier=str(getattr(candidate, "identifier")),
                        symbol=str(getattr(instrument, "symbol")),
                        rank=rank,
                        rationale=(
                            f"{getattr(instrument, 'symbol')} ranks #{rank} as a certified "
                            f"{view.kind.value} expression because directness, expected edge, "
                            "flow, expectations, liquidity, cost, and diversification were compared together."
                        ),
                        limitations=limitations,
                        evidence_identifiers=tuple(
                            dict.fromkeys(
                                (
                                    *tuple(getattr(candidate, "evidence_identifiers", ()) or ()),
                                    posture.identifier,
                                    view.identifier,
                                )
                            )
                        ),
                        **values,
                    )
                )
        covered = {item.view_identifier for item in expressions}
        uncovered = tuple(item.identifier for item in views if item.identifier not in covered)
        return ViewExpressionSet(
            identifier=f"view-expression-set:{posture.as_of.isoformat()}:{_hash([posture.identifier, *(item.identifier for item in views)])}",
            as_of=posture.as_of,
            posture_identifier=posture.identifier,
            views=views,
            expressions=tuple(expressions),
            uncovered_views=uncovered,
        )

    def enhance_directives(
        self,
        directives: Sequence[CandidateAllocationDirective],
        expression_set: ViewExpressionSet,
    ) -> tuple[CandidateAllocationDirective, ...]:
        result: list[CandidateAllocationDirective] = []
        for directive in directives:
            expression = expression_set.best_for_candidate(directive.candidate_identifier)
            if expression is None:
                result.append(directive)
                continue
            expression_alignment = 2.0 * expression.expression_score - 1.0
            alignment = max(
                -1.0,
                min(
                    1.0,
                    0.70 * directive.posture_alignment
                    + 0.30 * expression_alignment,
                ),
            )
            result.append(
                replace(
                    directive,
                    posture_alignment=round(alignment, 8),
                    rationale=(
                        directive.rationale
                        + f" Best certified view expression={expression.view_identifier}; "
                        + f"expression rank={expression.rank}; score={expression.expression_score:.0%}."
                    ),
                )
            )
        return tuple(result)

    def _views(self, posture: PortfolioPosture) -> tuple[InvestmentView, ...]:
        transition_by_regime = {item.regime: item.probability for item in posture.transitions}
        evidence = tuple(dict.fromkeys((posture.identifier, *posture.evidence)))
        change_conditions = posture.change_conditions or ("portfolio posture changes",)
        views: list[InvestmentView] = []

        def add(
            kind: InvestmentViewKind,
            classes: tuple[CandidateAssetClass, ...],
            direction: float,
            probability: float,
            rationale: str,
            catalysts: tuple[str, ...],
        ) -> None:
            views.append(
                InvestmentView(
                    identifier=f"investment-view:{kind.value}:{posture.as_of.isoformat()}",
                    as_of=posture.as_of,
                    kind=kind,
                    direction=direction,
                    confidence=posture.confidence,
                    transition_probability=_clip(probability),
                    preferred_asset_classes=classes,
                    rationale=rationale,
                    catalysts=catalysts,
                    invalidation_conditions=tuple(change_conditions),
                    evidence_identifiers=evidence,
                )
            )

        if posture.regime in {
            PortfolioRegime.RISK_ON_GROWTH,
            PortfolioRegime.RISK_ON_DISINFLATION,
        }:
            add(
                InvestmentViewKind.PRODUCTIVE_RISK,
                self._PRODUCTIVE,
                1.0,
                transition_by_regime.get(posture.regime, posture.confidence),
                "The governed posture favors productive risk, so certified growth, equity, real-estate, and alternative expressions must compete for capital.",
                ("growth and liquidity remain supportive", "breadth and revisions confirm"),
            )
        if posture.regime is PortfolioRegime.RISK_OFF_RECESSION:
            add(
                InvestmentViewKind.DEFENSIVE_DURATION,
                self._DEFENSIVE,
                1.0,
                transition_by_regime.get(posture.regime, posture.confidence),
                "Recessionary risk-off conditions favor defensive income and duration when inflation and sovereign risk permit.",
                ("growth deteriorates", "inflation and policy permit duration"),
            )
        if posture.regime is PortfolioRegime.RISK_OFF_INFLATION:
            add(
                InvestmentViewKind.INFLATION_PROTECTION,
                self._INFLATION,
                1.0,
                transition_by_regime.get(posture.regime, posture.confidence),
                "Inflationary risk-off conditions require real-asset and short-duration inflation-sensitive expressions rather than a generic bond rotation.",
                ("inflation persistence", "real yields and supply constraints"),
            )
        if posture.regime is PortfolioRegime.RISK_OFF_FUNDING_STRESS:
            add(
                InvestmentViewKind.DOLLAR_STRENGTH,
                self._DOLLAR,
                1.0,
                transition_by_regime.get(posture.regime, posture.confidence),
                "Funding stress raises the value of liquid dollar exposure and instruments that benefit from dollar scarcity.",
                ("funding stress persists", "dollar and liquidity evidence confirm"),
            )
        if PortfolioSleeve.DOLLAR_LIQUIDITY in posture.preferred_sleeves:
            add(
                InvestmentViewKind.LIQUIDITY_RESERVE,
                self._DOLLAR,
                1.0,
                posture.dollar_liquidity.midpoint,
                "The posture explicitly prefers dollar liquidity, so cash equivalents, Treasuries, and certified currency expressions must compete rather than remain an unexamined residual.",
                ("cash hurdle remains competitive", "liquidity preference persists"),
            )
        if posture.regime is PortfolioRegime.BALANCED_TRANSITION or not views:
            add(
                InvestmentViewKind.DIVERSIFICATION,
                self._DIVERSIFIERS,
                1.0,
                max(0.25, posture.confidence),
                "A balanced transition requires diversified, low-overlap expressions across certified sleeves while the next regime is uncertain.",
                ("cross-asset diversification remains effective", "no dominant regime emerges"),
            )
        return tuple(dict.fromkeys(views))

    @staticmethod
    def _directness(view: InvestmentView, candidate: object) -> float:
        instrument = getattr(candidate, "instrument")
        asset_class = getattr(instrument, "asset_class")
        symbol = str(getattr(instrument, "symbol", "")).upper()
        name = str(getattr(instrument, "name", "")).lower()
        if view.kind is InvestmentViewKind.PRODUCTIVE_RISK:
            return 0.95 if asset_class in {CandidateAssetClass.US_EQUITY, CandidateAssetClass.INTERNATIONAL_EQUITY} else 0.75
        if view.kind is InvestmentViewKind.DEFENSIVE_DURATION:
            if asset_class is CandidateAssetClass.FIXED_INCOME:
                duration = getattr(instrument, "effective_duration_years", None)
                return _clip(0.70 + min(float(duration or 0.0), 10.0) / 40.0)
            return 0.65 if asset_class is CandidateAssetClass.CASH_EQUIVALENT else 0.45
        if view.kind in {InvestmentViewKind.DOLLAR_STRENGTH, InvestmentViewKind.LIQUIDITY_RESERVE}:
            if asset_class is CandidateAssetClass.FX and ("USD" in symbol or "dollar" in name):
                return 1.0
            if asset_class is CandidateAssetClass.CASH_EQUIVALENT:
                return 0.95
            if bool(getattr(instrument, "is_us_treasury", False)):
                return 0.90
            return 0.55
        if view.kind is InvestmentViewKind.INFLATION_PROTECTION:
            if asset_class is CandidateAssetClass.COMMODITY:
                return 0.95
            if "tips" in name or "inflation" in name:
                return 0.95
            return 0.65
        return 0.70


class PositionLifecycleStage(str, Enum):
    OBSERVE = "observe"
    INITIATE = "initiate"
    VALIDATE = "validate"
    ADD = "add"
    HOLD = "hold"
    TRIM = "trim"
    EXIT = "exit"
    REENTER_ELIGIBLE = "reenter_eligible"


@dataclass(frozen=True, slots=True)
class PositionLifecycleDirective:
    candidate_identifier: str
    symbol: str
    prior_weight: float
    target_weight: float
    stage: PositionLifecycleStage
    thesis_state: str
    expression_score: float
    rationale: str
    validation_milestones: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    monitoring_indicators: tuple[str, ...]
    next_review_at: datetime
    required_cio_review: bool

    def __post_init__(self) -> None:
        for field_name in ("candidate_identifier", "symbol", "thesis_state", "rationale"):
            value = _text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(self, field_name, value.upper() if field_name == "symbol" else value)
        for field_name in ("prior_weight", "target_weight", "expression_score"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.stage, PositionLifecycleStage):
            raise TypeError("stage must be PositionLifecycleStage")
        for field_name, minimum in (
            ("validation_milestones", 1),
            ("invalidation_conditions", 1),
            ("monitoring_indicators", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        _aware(self.next_review_at, field_name="next_review_at")
        if not isinstance(self.required_cio_review, bool):
            raise TypeError("required_cio_review must be bool")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        payload["next_review_at"] = self.next_review_at.isoformat()
        payload["validation_milestones"] = list(self.validation_milestones)
        payload["invalidation_conditions"] = list(self.invalidation_conditions)
        payload["monitoring_indicators"] = list(self.monitoring_indicators)
        payload["cio_action_authority"] = False
        return payload


@dataclass(frozen=True, slots=True)
class PositionLifecyclePlan:
    identifier: str
    as_of: datetime
    directives: tuple[PositionLifecycleDirective, ...]
    model_version: str = "position-lifecycle.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.directives, tuple) or not all(
            isinstance(item, PositionLifecycleDirective) for item in self.directives
        ):
            raise TypeError("directives must contain PositionLifecycleDirective values")
        identifiers = tuple(item.candidate_identifier for item in self.directives)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("lifecycle directives must be unique by candidate")
        object.__setattr__(self, "model_version", _text(self.model_version, field_name="model_version"))

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "directives": [item.to_dict() for item in self.directives],
            "model_version": self.model_version,
            "cio_action_authority": False,
        }


class PositionLifecycleEngine:
    version = "position-lifecycle-engine.v1"

    def build(
        self,
        *,
        as_of: datetime,
        candidates: Sequence[object],
        decisions: Sequence[object],
        theses: Sequence[object],
        expression_set: ViewExpressionSet,
        portfolio: object,
        construction: object | None,
    ) -> PositionLifecyclePlan:
        timestamp = _aware(as_of, field_name="as_of")
        decision_by_candidate = {
            str(getattr(item, "candidate_identifier")): item for item in decisions
        }
        thesis_by_candidate = {
            str(getattr(item, "candidate_identifier")): item for item in theses
        }
        target_weights = dict(getattr(construction, "target_weights", ()) or ())
        directives: list[PositionLifecycleDirective] = []
        for candidate in candidates:
            identifier = str(getattr(candidate, "identifier"))
            instrument = getattr(candidate, "instrument")
            symbol = str(getattr(instrument, "symbol"))
            decision = decision_by_candidate.get(identifier)
            thesis = thesis_by_candidate.get(identifier)
            action = getattr(decision, "action", CIOAction.WATCH)
            prior_weight = float(getattr(candidate, "current_portfolio_weight", 0.0))
            target_weight = float(
                target_weights.get(
                    symbol.upper(),
                    getattr(decision, "recommended_position_weight", None)
                    if decision is not None
                    else prior_weight,
                )
                or 0.0
            )
            expression = expression_set.best_for_candidate(identifier)
            expression_score = 0.0 if expression is None else expression.expression_score
            thesis_state_value = getattr(thesis, "state", ThesisState.CANDIDATE)
            thesis_state = str(getattr(thesis_state_value, "value", thesis_state_value))
            stage = self._stage(
                action=action,
                prior_weight=prior_weight,
                target_weight=target_weight,
                thesis_state=thesis_state_value,
                expression_score=expression_score,
            )
            requires_review = stage in {
                PositionLifecycleStage.ADD,
                PositionLifecycleStage.TRIM,
                PositionLifecycleStage.EXIT,
                PositionLifecycleStage.REENTER_ELIGIBLE,
            }
            catalysts = tuple(getattr(candidate, "primary_catalysts", ()) or ())
            milestones = tuple(
                dict.fromkeys(
                    (
                        *catalysts[:3],
                        "expected return and expectations gap remain positive after refreshed evidence",
                        "capital-flow direction does not materially reverse before scaling",
                    )
                )
            )
            directives.append(
                PositionLifecycleDirective(
                    candidate_identifier=identifier,
                    symbol=symbol,
                    prior_weight=prior_weight,
                    target_weight=_clip(target_weight),
                    stage=stage,
                    thesis_state=thesis_state,
                    expression_score=expression_score,
                    rationale=self._rationale(stage, action, expression_score),
                    validation_milestones=milestones,
                    invalidation_conditions=tuple(getattr(candidate, "invalidation_conditions", ()) or ("thesis invalidated",)),
                    monitoring_indicators=tuple(getattr(candidate, "monitoring_indicators", ()) or ("price",)),
                    next_review_at=getattr(candidate, "review_at"),
                    required_cio_review=requires_review,
                )
            )
        return PositionLifecyclePlan(
            identifier=f"position-lifecycle-plan:{timestamp.isoformat()}:{_hash([item.candidate_identifier for item in directives])}",
            as_of=timestamp,
            directives=tuple(directives),
        )

    @staticmethod
    def _stage(
        *,
        action: object,
        prior_weight: float,
        target_weight: float,
        thesis_state: object,
        expression_score: float,
    ) -> PositionLifecycleStage:
        if action is CIOAction.EXIT or target_weight <= 0.0 < prior_weight:
            return PositionLifecycleStage.EXIT
        if action is CIOAction.REDUCE or target_weight < prior_weight - 0.000001:
            return PositionLifecycleStage.TRIM
        if action is CIOAction.BUY and prior_weight <= 0.0 and target_weight > 0.0:
            return PositionLifecycleStage.INITIATE
        if action is CIOAction.INCREASE or target_weight > prior_weight + 0.000001:
            return PositionLifecycleStage.ADD
        if prior_weight > 0.0 and thesis_state in {ThesisState.ACTIVE, ThesisState.UNDER_REVIEW}:
            return PositionLifecycleStage.VALIDATE
        if prior_weight > 0.0:
            return PositionLifecycleStage.HOLD
        if thesis_state in {ThesisState.EXITED, ThesisState.INVALIDATED} and expression_score >= 0.65:
            return PositionLifecycleStage.REENTER_ELIGIBLE
        return PositionLifecycleStage.OBSERVE

    @staticmethod
    def _rationale(stage: PositionLifecycleStage, action: object, expression_score: float) -> str:
        return (
            f"Lifecycle stage={stage.value}; CIO action={getattr(action, 'value', action)}; "
            f"best certified expression score={expression_score:.0%}. The lifecycle stage is a monitoring and CIO-review contract, not a trade instruction."
        )


class ReactiveTriggerKind(str, Enum):
    FLOW_REVERSAL = "flow_reversal"
    EXPECTATIONS_GAP = "expectations_gap"
    REGIME_TRANSITION = "regime_transition"
    RATES_CREDIT = "rates_credit"
    VOLATILITY_BREADTH = "volatility_breadth"
    EARNINGS_GUIDANCE = "earnings_guidance"
    THESIS_INVALIDATION = "thesis_invalidation"
    REPLACEMENT_OPPORTUNITY = "replacement_opportunity"
    RISK_BUDGET = "risk_budget"
    CATALYST = "catalyst"


@dataclass(frozen=True, slots=True)
class ReactiveDependency:
    identifier: str
    kind: ReactiveTriggerKind
    affected_candidates: tuple[str, ...]
    affected_sleeves: tuple[str, ...]
    evidence_inputs: tuple[str, ...]
    material_change: str
    incremental_reassessment: bool
    full_cycle_required: bool
    priority: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        if not isinstance(self.kind, ReactiveTriggerKind):
            raise TypeError("kind must be ReactiveTriggerKind")
        for field_name in ("affected_candidates", "affected_sleeves", "evidence_inputs"):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=1),
            )
        object.__setattr__(self, "material_change", _text(self.material_change, field_name="material_change"))
        if not isinstance(self.incremental_reassessment, bool) or not isinstance(self.full_cycle_required, bool):
            raise TypeError("reassessment flags must be bool")
        object.__setattr__(self, "priority", _ratio(self.priority, field_name="priority"))

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["affected_candidates"] = list(self.affected_candidates)
        payload["affected_sleeves"] = list(self.affected_sleeves)
        payload["evidence_inputs"] = list(self.evidence_inputs)
        payload["reassessment_authority"] = False
        return payload


@dataclass(frozen=True, slots=True)
class ReactiveMonitoringPlan:
    identifier: str
    as_of: datetime
    dependencies: tuple[ReactiveDependency, ...]
    model_version: str = "reactive-monitoring-plan.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, ReactiveDependency) for item in self.dependencies
        ):
            raise TypeError("dependencies must contain ReactiveDependency values")
        identifiers = tuple(item.identifier for item in self.dependencies)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("reactive dependency identifiers must be unique")
        object.__setattr__(self, "model_version", _text(self.model_version, field_name="model_version"))

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "dependencies": [item.to_dict() for item in self.dependencies],
            "model_version": self.model_version,
            "reassessment_authority": False,
        }


class ReactiveMonitoringEngine:
    version = "reactive-monitoring-engine.v1"

    def build(
        self,
        *,
        posture: PortfolioPosture,
        expression_set: ViewExpressionSet,
        lifecycle: PositionLifecyclePlan,
    ) -> ReactiveMonitoringPlan:
        candidates_by_view: dict[str, list[str]] = {}
        for expression in expression_set.expressions:
            if expression.rank <= 10:
                candidates_by_view.setdefault(expression.view_identifier, []).append(
                    expression.candidate_identifier
                )
        dependencies: list[ReactiveDependency] = []
        for view in expression_set.views:
            affected = tuple(dict.fromkeys(candidates_by_view.get(view.identifier, ())))
            if not affected:
                continue
            sleeve = self._sleeve(view.kind)
            dependencies.extend(
                (
                    ReactiveDependency(
                        identifier=f"reactive:{view.identifier}:flow",
                        kind=ReactiveTriggerKind.FLOW_REVERSAL,
                        affected_candidates=affected,
                        affected_sleeves=(sleeve,),
                        evidence_inputs=("signed_dollar_flow", "volume_impulse", "flow_persistence", "flow_crowding"),
                        material_change="flow direction reverses, persistence breaks, or crowding materially rises",
                        incremental_reassessment=True,
                        full_cycle_required=False,
                        priority=max(0.40, view.confidence),
                    ),
                    ReactiveDependency(
                        identifier=f"reactive:{view.identifier}:expectations",
                        kind=ReactiveTriggerKind.EXPECTATIONS_GAP,
                        affected_candidates=affected,
                        affected_sleeves=(sleeve,),
                        evidence_inputs=("expected_market_surprise", "priced_in_score", "volatility", "catalyst_timing"),
                        material_change="the expectations gap changes sign or becomes materially smaller",
                        incremental_reassessment=True,
                        full_cycle_required=False,
                        priority=max(0.40, view.confidence),
                    ),
                )
            )
        all_candidates = tuple(
            dict.fromkeys(item.candidate_identifier for item in lifecycle.directives)
        ) or ("portfolio",)
        dependencies.append(
            ReactiveDependency(
                identifier=f"reactive:{posture.identifier}:regime",
                kind=ReactiveTriggerKind.REGIME_TRANSITION,
                affected_candidates=all_candidates,
                affected_sleeves=tuple(item.value for item in posture.preferred_sleeves) or ("all",),
                evidence_inputs=("growth", "inflation", "liquidity", "credit", "currency", "breadth"),
                material_change="the leading transition probability or causal regime changes materially",
                incremental_reassessment=False,
                full_cycle_required=True,
                priority=max(0.50, posture.confidence),
            )
        )
        for item in lifecycle.directives:
            if item.stage in {
                PositionLifecycleStage.INITIATE,
                PositionLifecycleStage.VALIDATE,
                PositionLifecycleStage.ADD,
                PositionLifecycleStage.TRIM,
                PositionLifecycleStage.EXIT,
                PositionLifecycleStage.REENTER_ELIGIBLE,
            }:
                dependencies.append(
                    ReactiveDependency(
                        identifier=f"reactive:lifecycle:{item.candidate_identifier}",
                        kind=(
                            ReactiveTriggerKind.THESIS_INVALIDATION
                            if item.stage in {PositionLifecycleStage.TRIM, PositionLifecycleStage.EXIT}
                            else ReactiveTriggerKind.CATALYST
                        ),
                        affected_candidates=(item.candidate_identifier,),
                        affected_sleeves=("position_lifecycle",),
                        evidence_inputs=tuple(
                            dict.fromkeys(
                                (
                                    *item.monitoring_indicators,
                                    *item.invalidation_conditions,
                                )
                            )
                        ),
                        material_change=(
                            "a validation milestone, invalidation condition, catalyst, or superior replacement is observed"
                        ),
                        incremental_reassessment=True,
                        full_cycle_required=False,
                        priority=max(0.50, item.expression_score),
                    )
                )
        return ReactiveMonitoringPlan(
            identifier=f"reactive-monitoring-plan:{posture.as_of.isoformat()}:{_hash([item.identifier for item in dependencies])}",
            as_of=posture.as_of,
            dependencies=tuple(dependencies),
        )

    @staticmethod
    def _sleeve(kind: InvestmentViewKind) -> str:
        return {
            InvestmentViewKind.PRODUCTIVE_RISK: PortfolioSleeve.PRODUCTIVE_RISK.value,
            InvestmentViewKind.DEFENSIVE_DURATION: PortfolioSleeve.DEFENSIVE_INCOME.value,
            InvestmentViewKind.DOLLAR_STRENGTH: PortfolioSleeve.DOLLAR_LIQUIDITY.value,
            InvestmentViewKind.LIQUIDITY_RESERVE: PortfolioSleeve.DOLLAR_LIQUIDITY.value,
            InvestmentViewKind.INFLATION_PROTECTION: PortfolioSleeve.INFLATION_REAL_ASSETS.value,
            InvestmentViewKind.DIVERSIFICATION: PortfolioSleeve.DIVERSIFIERS.value,
        }[kind]


@dataclass(frozen=True, slots=True)
class CompoundingAccountabilitySnapshot:
    identifier: str
    as_of: datetime
    selected_alternative_identifier: str | None
    selected_estimated_compound_return: float
    current_estimated_compound_return: float
    cash_estimated_return: float
    estimated_edge_vs_current: float
    estimated_edge_vs_cash: float
    cash_opportunity_cost: float
    productive_risk_deployment_gap: float
    positive_edge_nonownership_count: int
    positive_edge_nonownership_candidates: tuple[str, ...]
    turnover_drag: float
    construction_improvement: float
    limitations: tuple[str, ...]
    model_version: str = "compounding-accountability.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        if self.selected_alternative_identifier is not None:
            object.__setattr__(
                self,
                "selected_alternative_identifier",
                _text(self.selected_alternative_identifier, field_name="selected_alternative_identifier"),
            )
        for field_name in (
            "selected_estimated_compound_return",
            "current_estimated_compound_return",
            "cash_estimated_return",
            "estimated_edge_vs_current",
            "estimated_edge_vs_cash",
            "cash_opportunity_cost",
            "productive_risk_deployment_gap",
            "turnover_drag",
            "construction_improvement",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name=field_name))
        if isinstance(self.positive_edge_nonownership_count, bool) or not isinstance(
            self.positive_edge_nonownership_count, int
        ) or self.positive_edge_nonownership_count < 0:
            raise ValueError("positive_edge_nonownership_count must be a non-negative integer")
        object.__setattr__(
            self,
            "positive_edge_nonownership_candidates",
            _texts(self.positive_edge_nonownership_candidates, field_name="positive_edge_nonownership_candidates"),
        )
        if self.positive_edge_nonownership_count != len(self.positive_edge_nonownership_candidates):
            raise ValueError("positive-edge candidate count is inconsistent")
        object.__setattr__(self, "limitations", _texts(self.limitations, field_name="limitations", minimum=1))
        object.__setattr__(self, "model_version", _text(self.model_version, field_name="model_version"))

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["positive_edge_nonownership_candidates"] = list(self.positive_edge_nonownership_candidates)
        payload["limitations"] = list(self.limitations)
        payload["automatic_policy_change"] = False
        payload["investment_authority"] = False
        return payload


class CompoundingAccountabilityEngine:
    version = "compounding-accountability-engine.v1"

    def build(
        self,
        *,
        posture: PortfolioPosture,
        alternatives: CompoundingPortfolioAlternativeSet,
        candidates: Sequence[object],
        decisions: Sequence[object],
        construction: object | None,
    ) -> CompoundingAccountabilitySnapshot:
        alternative_by_kind = {item.kind.value: item for item in alternatives.alternatives}
        alternative_by_id = {item.identifier: item for item in alternatives.alternatives}
        selected = (
            alternative_by_id.get(alternatives.selected_alternative_identifier)
            if alternatives.selected_alternative_identifier is not None
            else None
        )
        current = alternative_by_kind.get("current")
        cash = alternative_by_kind.get("all_cash")
        selected_return = (
            float(selected.estimated_compound_return)
            if selected is not None
            else float(cash.estimated_compound_return if cash is not None else 0.0)
        )
        current_return = float(current.estimated_compound_return if current is not None else 0.0)
        cash_return = float(cash.estimated_compound_return if cash is not None else 0.0)
        selected_sleeves = dict(getattr(selected, "sleeve_weights", ()) or ())
        productive_target = float(selected_sleeves.get(PortfolioSleeve.PRODUCTIVE_RISK.value, 0.0))
        productive_gap = max(0.0, posture.productive_risk.minimum - productive_target)
        action_by_candidate = {
            str(getattr(item, "candidate_identifier")): getattr(item, "action", CIOAction.WATCH)
            for item in decisions
        }
        positive_nonownership: list[str] = []
        for candidate in candidates:
            candidate_identifier = str(getattr(candidate, "identifier"))
            action = action_by_candidate.get(candidate_identifier, CIOAction.WATCH)
            current_weight = float(getattr(candidate, "current_portfolio_weight", 0.0))
            edge = float(getattr(candidate, "net_expected_return", 0.0)) - float(
                getattr(candidate, "opportunity_cost_return", 0.0)
            )
            if (
                edge > 0.0
                and current_weight <= 0.0
                and action not in {CIOAction.BUY, CIOAction.INCREASE}
            ):
                positive_nonownership.append(candidate_identifier)
        turnover_drag = float(getattr(construction, "estimated_cost_return", 0.0) or 0.0)
        construction_improvement = float(
            getattr(construction, "expected_return_improvement", 0.0) or 0.0
        )
        return CompoundingAccountabilitySnapshot(
            identifier=f"compounding-accountability:{posture.as_of.isoformat()}:{_hash([alternatives.identifier, selected_return, positive_nonownership])}",
            as_of=posture.as_of,
            selected_alternative_identifier=alternatives.selected_alternative_identifier,
            selected_estimated_compound_return=selected_return,
            current_estimated_compound_return=current_return,
            cash_estimated_return=cash_return,
            estimated_edge_vs_current=selected_return - current_return,
            estimated_edge_vs_cash=selected_return - cash_return,
            cash_opportunity_cost=max(0.0, selected_return - cash_return),
            productive_risk_deployment_gap=productive_gap,
            positive_edge_nonownership_count=len(positive_nonownership),
            positive_edge_nonownership_candidates=tuple(positive_nonownership),
            turnover_drag=turnover_drag,
            construction_improvement=construction_improvement,
            limitations=(
                "This is prospective accountability; realized false positives, false negatives, timing, sizing, and regime value remain measured by the existing point-in-time and opportunity-outcome evaluators after their horizons mature",
                "No metric may automatically lower a threshold, change policy, authorize capital, or claim future performance",
            ),
        )


class SQLiteActiveInvestorStore:
    """Append-only hash chain for expression, lifecycle, monitoring, and accountability."""

    _TABLE = "active_investor_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    cycle_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS active_investor_cycle_sequence
                ON {self._TABLE} (cycle_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'active investor events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'active investor events are append-only'); END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append_cycle(
        self,
        *,
        cycle_identifier: str,
        expressions: ViewExpressionSet,
        lifecycle: PositionLifecyclePlan,
        reactive: ReactiveMonitoringPlan,
        accountability: CompoundingAccountabilitySnapshot,
        code_version: str,
    ) -> None:
        for event_type, value in (
            ("view_expressions", expressions),
            ("position_lifecycle", lifecycle),
            ("reactive_monitoring", reactive),
            ("compounding_accountability", accountability),
        ):
            payload = value.to_dict()
            payload["code_version"] = _text(code_version, field_name="code_version")
            self._append(
                event_identifier=str(payload["identifier"]),
                cycle_identifier=cycle_identifier,
                event_type=event_type,
                occurred_at=value.as_of,
                payload=payload,
            )

    def _append(
        self,
        *,
        event_identifier: str,
        cycle_identifier: str,
        event_type: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> None:
        identifier = _text(event_identifier, field_name="event_identifier")
        cycle = _text(cycle_identifier, field_name="cycle_identifier")
        kind = _text(event_type, field_name="event_type")
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError("active-investor event identifier conflict")
                return
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = _hash(
                {
                    "sequence": sequence,
                    "event_identifier": identifier,
                    "cycle_identifier": cycle,
                    "event_type": kind,
                    "occurred_at": timestamp,
                    "payload_json": payload_json,
                    "previous_hash": previous_hash,
                }
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, cycle_identifier, event_type,
                    occurred_at, payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    cycle,
                    kind,
                    timestamp,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM {self._TABLE} ORDER BY sequence").fetchall()
        previous = self._GENESIS
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected or str(row["previous_hash"]) != previous:
                raise ValueError("active-investor event chain is invalid")
            expected_hash = _hash(
                {
                    "sequence": expected,
                    "event_identifier": str(row["event_identifier"]),
                    "cycle_identifier": str(row["cycle_identifier"]),
                    "event_type": str(row["event_type"]),
                    "occurred_at": str(row["occurred_at"]),
                    "payload_json": str(row["payload_json"]),
                    "previous_hash": previous,
                }
            )
            if str(row["content_hash"]) != expected_hash:
                raise ValueError("active-investor event content hash is invalid")
            previous = expected_hash
        return True


__all__ = [
    "CompoundingAccountabilityEngine",
    "CompoundingAccountabilitySnapshot",
    "InvestableExpression",
    "InvestmentView",
    "InvestmentViewKind",
    "PositionLifecycleDirective",
    "PositionLifecycleEngine",
    "PositionLifecyclePlan",
    "PositionLifecycleStage",
    "ReactiveDependency",
    "ReactiveMonitoringEngine",
    "ReactiveMonitoringPlan",
    "ReactiveTriggerKind",
    "SQLiteActiveInvestorStore",
    "ViewExpressionSet",
    "ViewToExpressionEngine",
]
