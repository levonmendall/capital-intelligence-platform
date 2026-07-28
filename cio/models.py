"""Canonical quantitative candidate and CIO decision contracts.

These models are the first implementation of the common decision schema in
GOVERNING_SPECIFICATION.md.  They are intentionally independent of presentation,
database, provider, and legacy weighted-consensus code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class CandidateAssetClass(str, Enum):
    """Recommendation-scope classification, distinct from evidence coverage."""

    US_EQUITY = "us_equity"
    US_ETF = "us_etf"
    CASH_EQUIVALENT = "cash_equivalent"
    FIXED_INCOME = "fixed_income"
    INTERNATIONAL_EQUITY = "international_equity"
    COMMODITY = "commodity"
    FX = "fx"
    CRYPTO = "crypto"
    REAL_ESTATE = "real_estate"
    FUTURE = "future"
    OPTION = "option"
    VOLATILITY = "volatility"
    ALTERNATIVE = "alternative"
    OTHER = "other"


class CIOAction(str, Enum):
    """Only actions the Chief Investment Officer may issue."""

    BUY = "buy"
    INCREASE = "increase"
    HOLD = "hold"
    REDUCE = "reduce"
    EXIT = "exit"
    WATCH = "watch"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_SUPERIOR_OPPORTUNITY = "no_superior_opportunity"
    NO_MATERIAL_CHANGE = "no_material_change"


class SpecialistRole(str, Enum):
    """The five independent analytical roles preceding CIO synthesis."""

    MACRO_ECONOMIC = "macro_economic_strategist"
    MARKET = "market_strategist"
    FUNDAMENTAL_VALUATION = "fundamental_valuation_analyst"
    PORTFOLIO_RISK = "portfolio_risk_manager"
    EVIDENCE_GOVERNANCE = "evidence_governance_officer"


class SpecialistPosition(str, Enum):
    """Analytical stance; not a user-facing portfolio action."""

    SUPPORTIVE = "supportive"
    NEUTRAL = "neutral"
    OPPOSED = "opposed"
    ABSTAIN = "abstain"


class ThesisState(str, Enum):
    """Living-thesis lifecycle states required by the governing specification."""

    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    STRENGTHENING = "strengthening"
    STABLE = "stable"
    WEAKENING = "weakening"
    REDUCED = "reduced"
    EXITED = "exited"
    INVALIDATED = "invalidated"
    EVALUATED = "evaluated"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


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
    return _finite(
        value,
        field_name=field_name,
        minimum=0.0,
        maximum=1.0,
    )


def _text_tuple(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(
            f"{field_name} must contain at least {minimum} item(s)"
        )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class EvidenceQuality:
    """Disclosed evidence dimensions; repeated reporting is not independence."""

    reliability: float
    freshness: float
    relevance: float
    independence: float
    completeness: float
    point_in_time_integrity: float

    def __post_init__(self) -> None:
        for field_name in (
            "reliability",
            "freshness",
            "relevance",
            "independence",
            "completeness",
            "point_in_time_integrity",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )

    @property
    def score(self) -> float:
        """Transparent equal-weight diagnostic, not a substitute for dimensions."""

        return round(
            sum(
                (
                    self.reliability,
                    self.freshness,
                    self.relevance,
                    self.independence,
                    self.completeness,
                    self.point_in_time_integrity,
                )
            )
            / 6.0,
            6,
        )

    @property
    def ceiling(self) -> float:
        """Strictest disclosed dimension limits confidence."""

        return min(
            self.reliability,
            self.freshness,
            self.relevance,
            self.independence,
            self.completeness,
            self.point_in_time_integrity,
        )


@dataclass(frozen=True, slots=True)
class CandidateInstrument:
    """Point-in-time instrument facts used by recommendation-universe policy."""

    instrument_id: str
    symbol: str
    name: str
    asset_class: CandidateAssetClass
    venue: str
    country_code: str
    average_daily_dollar_volume: float
    data_age_hours: float
    analytical_coverage: float
    security_master_snapshot_identifier: str
    security_master_record_identifiers: tuple[str, ...]
    is_us_treasury: bool = False
    effective_duration_years: float | None = None
    instrument_type: str = "other"
    economic_exposure_class: CandidateAssetClass | None = None
    leverage_multiplier: float = 1.0
    uses_derivatives: bool = False
    replication_method: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "symbol",
            "name",
            "venue",
            "country_code",
        ):
            normalized = _required_text(
                getattr(self, field_name),
                field_name=field_name,
            )
            if field_name in {"symbol", "venue", "country_code"}:
                normalized = normalized.upper()
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(
            self,
            "security_master_snapshot_identifier",
            _required_text(
                self.security_master_snapshot_identifier,
                field_name="security_master_snapshot_identifier",
            ),
        )
        object.__setattr__(
            self,
            "security_master_record_identifiers",
            _text_tuple(
                self.security_master_record_identifiers,
                field_name="security_master_record_identifiers",
                minimum=1,
            ),
        )
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be a CandidateAssetClass")
        object.__setattr__(
            self,
            "average_daily_dollar_volume",
            _finite(
                self.average_daily_dollar_volume,
                field_name="average_daily_dollar_volume",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "data_age_hours",
            _finite(
                self.data_age_hours,
                field_name="data_age_hours",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "analytical_coverage",
            _ratio(
                self.analytical_coverage,
                field_name="analytical_coverage",
            ),
        )
        if not isinstance(self.is_us_treasury, bool):
            raise TypeError("is_us_treasury must be a bool")
        if self.effective_duration_years is not None:
            object.__setattr__(
                self,
                "effective_duration_years",
                _finite(
                    self.effective_duration_years,
                    field_name="effective_duration_years",
                    minimum=0.0,
                ),
            )
        object.__setattr__(
            self,
            "instrument_type",
            _required_text(
                self.instrument_type,
                field_name="instrument_type",
            ).lower(),
        )
        if self.economic_exposure_class is not None and not isinstance(
            self.economic_exposure_class,
            CandidateAssetClass,
        ):
            raise TypeError(
                "economic_exposure_class must be a CandidateAssetClass"
            )
        object.__setattr__(
            self,
            "leverage_multiplier",
            _finite(
                self.leverage_multiplier,
                field_name="leverage_multiplier",
                minimum=-10.0,
                maximum=10.0,
            ),
        )
        if abs(self.leverage_multiplier) < 0.00000001:
            raise ValueError("leverage_multiplier cannot be zero")
        if not isinstance(self.uses_derivatives, bool):
            raise TypeError("uses_derivatives must be a bool")
        if self.replication_method is not None:
            object.__setattr__(
                self,
                "replication_method",
                _required_text(
                    self.replication_method,
                    field_name="replication_method",
                ).lower(),
            )


@dataclass(frozen=True, slots=True)
class CandidateDecisionRecord:
    """Comparable quantitative evidence package submitted for specialist review."""

    identifier: str
    as_of: datetime
    schema_version: str
    instrument: CandidateInstrument
    current_price: float
    decision_horizon_days: int
    base_case_return: float
    bull_case_return: float
    bear_case_return: float
    base_case_probability: float
    bull_case_probability: float
    bear_case_probability: float
    estimated_fair_value: float
    expected_upside: float
    expected_downside: float
    probability_of_success: float
    primary_catalysts: tuple[str, ...]
    key_risks: tuple[str, ...]
    critical_assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    evidence_quality: EvidenceQuality
    liquidity_score: float
    transaction_cost_bps: float
    slippage_bps: float
    opportunity_cost_return: float
    expected_portfolio_contribution: float
    current_portfolio_weight: float
    maximum_position_weight: float
    monitoring_indicators: tuple[str, ...]
    review_at: datetime
    evidence_identifiers: tuple[str, ...]
    model_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        _aware(self.review_at, field_name="review_at")
        if self.review_at <= self.as_of:
            raise ValueError("review_at must be later than as_of")
        if not isinstance(self.instrument, CandidateInstrument):
            raise TypeError("instrument must be a CandidateInstrument")
        object.__setattr__(
            self,
            "current_price",
            _finite(self.current_price, field_name="current_price", minimum=0.0),
        )
        if self.instrument.asset_class is not CandidateAssetClass.CASH_EQUIVALENT:
            if self.current_price <= 0.0:
                raise ValueError("current_price must be positive for traded assets")
        if isinstance(self.decision_horizon_days, bool) or not isinstance(
            self.decision_horizon_days, int
        ):
            raise TypeError("decision_horizon_days must be an integer")
        if self.decision_horizon_days < 1:
            raise ValueError("decision_horizon_days must be positive")
        for field_name in (
            "base_case_return",
            "bull_case_return",
            "bear_case_return",
            "expected_upside",
            "expected_downside",
            "opportunity_cost_return",
            "expected_portfolio_contribution",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "base_case_probability",
            "bull_case_probability",
            "bear_case_probability",
            "probability_of_success",
            "liquidity_score",
            "current_portfolio_weight",
            "maximum_position_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        probability_total = (
            self.base_case_probability
            + self.bull_case_probability
            + self.bear_case_probability
        )
        if abs(probability_total - 1.0) > 0.000001:
            raise ValueError("scenario probabilities must sum to 1.0")
        object.__setattr__(
            self,
            "estimated_fair_value",
            _finite(
                self.estimated_fair_value,
                field_name="estimated_fair_value",
                minimum=0.0,
            ),
        )
        for field_name in ("transaction_cost_bps", "slippage_bps"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        if self.current_portfolio_weight > self.maximum_position_weight:
            raise ValueError(
                "current_portfolio_weight cannot exceed maximum_position_weight"
            )
        if not isinstance(self.evidence_quality, EvidenceQuality):
            raise TypeError("evidence_quality must be EvidenceQuality")
        for field_name, minimum in (
            ("primary_catalysts", 1),
            ("key_risks", 1),
            ("critical_assumptions", 1),
            ("invalidation_conditions", 1),
            ("supporting_evidence", 1),
            ("contradictory_evidence", 0),
            ("monitoring_indicators", 1),
            ("evidence_identifiers", 1),
            ("model_versions", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )

    @property
    def probability_weighted_expected_return(self) -> float:
        return round(
            self.base_case_return * self.base_case_probability
            + self.bull_case_return * self.bull_case_probability
            + self.bear_case_return * self.bear_case_probability,
            8,
        )

    @property
    def implementation_cost_return(self) -> float:
        return round((self.transaction_cost_bps + self.slippage_bps) / 10_000, 8)

    @property
    def net_expected_return(self) -> float:
        return round(
            self.probability_weighted_expected_return
            - self.implementation_cost_return,
            8,
        )

    @property
    def opportunity_edge(self) -> float:
        return round(self.net_expected_return - self.opportunity_cost_return, 8)


@dataclass(frozen=True, slots=True)
class MaterialDissent:
    """Strongest opposing specialist conclusion preserved for CIO review."""

    opposing_role: SpecialistRole
    opposing_conclusion: str
    disagreement_reason: str
    resolving_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.opposing_role, SpecialistRole):
            raise TypeError("opposing_role must be a SpecialistRole")
        for field_name in ("opposing_conclusion", "disagreement_reason"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "resolving_evidence",
            _text_tuple(
                self.resolving_evidence,
                field_name="resolving_evidence",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class CIODecision:
    """Final action issued only by the Chief Investment Officer service."""

    identifier: str
    candidate_identifier: str
    as_of: datetime
    schema_version: str
    action: CIOAction
    final_confidence: float
    expected_return: float
    decision_horizon_days: int
    recommended_position_weight: float | None
    funding_source: str | None
    thesis: str
    rationale: str
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    key_assumptions: tuple[str, ...]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    portfolio_impact: str
    opportunity_cost: str
    dissent: MaterialDissent | None
    evidence_vetoes: tuple[str, ...]
    implementation_blocks: tuple[str, ...]
    monitoring_indicators: tuple[str, ...]
    review_at: datetime
    explanation: str
    policy_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "candidate_identifier",
            "schema_version",
            "thesis",
            "rationale",
            "portfolio_impact",
            "opportunity_cost",
            "explanation",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        _aware(self.review_at, field_name="review_at")
        if self.review_at <= self.as_of:
            raise ValueError("review_at must be later than as_of")
        if not isinstance(self.action, CIOAction):
            raise TypeError("action must be a CIOAction")
        object.__setattr__(
            self,
            "final_confidence",
            _ratio(self.final_confidence, field_name="final_confidence"),
        )
        object.__setattr__(
            self,
            "expected_return",
            _finite(self.expected_return, field_name="expected_return"),
        )
        if isinstance(self.decision_horizon_days, bool) or not isinstance(
            self.decision_horizon_days, int
        ):
            raise TypeError("decision_horizon_days must be an integer")
        if self.decision_horizon_days < 1:
            raise ValueError("decision_horizon_days must be positive")
        if self.recommended_position_weight is not None:
            object.__setattr__(
                self,
                "recommended_position_weight",
                _ratio(
                    self.recommended_position_weight,
                    field_name="recommended_position_weight",
                ),
            )
        if self.funding_source is not None:
            object.__setattr__(
                self,
                "funding_source",
                _required_text(self.funding_source, field_name="funding_source"),
            )
        if self.dissent is not None and not isinstance(
            self.dissent, MaterialDissent
        ):
            raise TypeError("dissent must be MaterialDissent or None")
        for field_name, minimum in (
            ("supporting_evidence", 1),
            ("contradictory_evidence", 0),
            ("key_assumptions", 1),
            ("catalysts", 1),
            ("risks", 1),
            ("invalidation_conditions", 1),
            ("evidence_vetoes", 0),
            ("implementation_blocks", 0),
            ("monitoring_indicators", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        action_requires_size = self.action in {
            CIOAction.BUY,
            CIOAction.INCREASE,
            CIOAction.REDUCE,
        }
        if action_requires_size and self.recommended_position_weight is None:
            raise ValueError(
                f"{self.action.value} requires a recommended_position_weight"
            )
        abstentions = {
            CIOAction.WATCH,
            CIOAction.INSUFFICIENT_EVIDENCE,
            CIOAction.NO_SUPERIOR_OPPORTUNITY,
            CIOAction.NO_MATERIAL_CHANGE,
        }
        if self.action in abstentions and self.recommended_position_weight is not None:
            raise ValueError("abstention decisions cannot recommend a position size")