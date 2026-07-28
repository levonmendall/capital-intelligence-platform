"""Deterministic independent specialist services for canonical CIO review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    IndependentSpecialistPacket,
    SpecialistAnalysis,
    SpecialistPosition,
    SpecialistRole,
)
from company import CompanyAnalysis, CompanyFactor


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


def _ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return round(normalized, 8)


def _bounded(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not -1.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between -1 and 1")
    return round(normalized, 8)


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


def _position(impact: float, threshold: float = 0.01) -> SpecialistPosition:
    if impact > threshold:
        return SpecialistPosition.SUPPORTIVE
    if impact < -threshold:
        return SpecialistPosition.OPPOSED
    return SpecialistPosition.NEUTRAL


@dataclass(frozen=True, slots=True)
class MacroSpecialistContext:
    as_of: datetime
    regime: str
    expected_return_impact: float
    confidence: float
    tailwinds: tuple[str, ...]
    headwinds: tuple[str, ...]
    systemic_risks: tuple[str, ...]
    scenarios: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "regime",
            _required_text(self.regime, field_name="regime"),
        )
        object.__setattr__(
            self,
            "expected_return_impact",
            _bounded(
                self.expected_return_impact,
                field_name="expected_return_impact",
            ),
        )
        object.__setattr__(
            self,
            "confidence",
            _ratio(self.confidence, field_name="confidence"),
        )
        for field_name, minimum in (
            ("tailwinds", 0),
            ("headwinds", 0),
            ("systemic_risks", 1),
            ("scenarios", 1),
            ("evidence_identifiers", 1),
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


@dataclass(frozen=True, slots=True)
class MarketSpecialistContext:
    as_of: datetime
    market_regime: str
    expected_return_impact: float
    confidence: float
    trend: float
    momentum: float
    breadth: float
    liquidity: float
    positioning: float
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    entry_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "market_regime",
            _required_text(
                self.market_regime,
                field_name="market_regime",
            ),
        )
        object.__setattr__(
            self,
            "expected_return_impact",
            _bounded(
                self.expected_return_impact,
                field_name="expected_return_impact",
            ),
        )
        object.__setattr__(
            self,
            "confidence",
            _ratio(self.confidence, field_name="confidence"),
        )
        for field_name in (
            "trend",
            "momentum",
            "breadth",
            "liquidity",
            "positioning",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name=field_name),
            )
        for field_name, minimum in (
            ("evidence", 1),
            ("risks", 1),
            ("entry_conditions", 1),
            ("evidence_identifiers", 0),
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


@dataclass(frozen=True, slots=True)
class ForecastScenarioAssessment:
    """Candidate-specific effect of one governed cross-asset forecast scenario."""

    label: str
    probability: float
    candidate_return_impact: float
    expected_path_drawdown: float
    rationale: str
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "label",
            _required_text(self.label, field_name="label"),
        )
        object.__setattr__(
            self,
            "probability",
            _ratio(self.probability, field_name="probability"),
        )
        object.__setattr__(
            self,
            "candidate_return_impact",
            _bounded(
                self.candidate_return_impact,
                field_name="candidate_return_impact",
            ),
        )
        drawdown = _bounded(
            self.expected_path_drawdown,
            field_name="expected_path_drawdown",
        )
        if drawdown > 0.0:
            raise ValueError("expected_path_drawdown must be zero or negative")
        object.__setattr__(self, "expected_path_drawdown", drawdown)
        object.__setattr__(
            self,
            "rationale",
            _required_text(self.rationale, field_name="rationale"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _text_tuple(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class CrossAssetForecastSpecialistContext:
    """Forward distribution evidence kept separate from market technicals."""

    as_of: datetime
    forecast_horizon_days: int
    scenarios: tuple[ForecastScenarioAssessment, ...]
    aggregate_confidence: float
    calibration_score: float
    model_agreement: float
    forecast_stability: float
    path_drawdown_probability: float
    cross_asset_signals: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    limitations: tuple[str, ...]
    change_conditions: tuple[str, ...]
    model_versions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if isinstance(self.forecast_horizon_days, bool) or not isinstance(
            self.forecast_horizon_days, int
        ):
            raise TypeError("forecast_horizon_days must be an integer")
        if self.forecast_horizon_days < 1:
            raise ValueError("forecast_horizon_days must be positive")
        if not isinstance(self.scenarios, tuple) or not all(
            isinstance(item, ForecastScenarioAssessment) for item in self.scenarios
        ):
            raise TypeError(
                "scenarios must contain ForecastScenarioAssessment values"
            )
        if len(self.scenarios) < 2:
            raise ValueError("forecast specialist requires at least two scenarios")
        labels = tuple(item.label for item in self.scenarios)
        if len(labels) != len(set(labels)):
            raise ValueError("forecast scenario labels must be unique")
        if abs(sum(item.probability for item in self.scenarios) - 1.0) > 0.000001:
            raise ValueError("forecast scenario probabilities must sum to 1.0")
        for field_name in (
            "aggregate_confidence",
            "calibration_score",
            "model_agreement",
            "forecast_stability",
            "path_drawdown_probability",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        for field_name, minimum in (
            ("cross_asset_signals", 1),
            ("contradictory_evidence", 0),
            ("limitations", 1),
            ("change_conditions", 1),
            ("model_versions", 1),
            ("evidence_identifiers", 1),
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
    def expected_return_impact(self) -> float:
        return round(
            sum(
                item.probability * item.candidate_return_impact
                for item in self.scenarios
            ),
            8,
        )

    @property
    def expected_path_drawdown(self) -> float:
        return round(
            sum(
                item.probability * item.expected_path_drawdown
                for item in self.scenarios
            ),
            8,
        )

    def horizon_alignment(self, decision_horizon_days: int) -> float:
        if isinstance(decision_horizon_days, bool) or not isinstance(
            decision_horizon_days, int
        ):
            raise TypeError("decision_horizon_days must be an integer")
        if decision_horizon_days < 1:
            raise ValueError("decision_horizon_days must be positive")
        shorter = min(decision_horizon_days, self.forecast_horizon_days)
        longer = max(decision_horizon_days, self.forecast_horizon_days)
        return round(shorter / longer, 8)


@dataclass(frozen=True, slots=True)
class AssetValuationSpecialistContext:
    """Independent asset-specific valuation evidence for non-company instruments."""

    as_of: datetime
    asset_class: CandidateAssetClass
    expected_return_impact: float
    confidence: float
    valuation_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    critical_assumptions: tuple[str, ...]
    risks: tuple[str, ...]
    limitations: tuple[str, ...]
    change_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        object.__setattr__(
            self,
            "expected_return_impact",
            _bounded(
                self.expected_return_impact,
                field_name="expected_return_impact",
            ),
        )
        object.__setattr__(
            self,
            "confidence",
            _ratio(self.confidence, field_name="confidence"),
        )
        for field_name, minimum in (
            ("valuation_evidence", 1),
            ("contradictory_evidence", 0),
            ("critical_assumptions", 1),
            ("risks", 1),
            ("limitations", 1),
            ("change_conditions", 1),
            ("evidence_identifiers", 1),
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


@dataclass(frozen=True, slots=True)
class PortfolioSpecialistContext:
    as_of: datetime
    proposed_position_weight: float | None
    funding_source: str | None
    expected_portfolio_contribution: float
    opportunity_cost_return: float
    constraint_evidence: tuple[str, ...]
    implementation_blocks: tuple[str, ...]
    review_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if self.proposed_position_weight is not None:
            object.__setattr__(
                self,
                "proposed_position_weight",
                _ratio(
                    self.proposed_position_weight,
                    field_name="proposed_position_weight",
                ),
            )
        if self.funding_source is not None:
            object.__setattr__(
                self,
                "funding_source",
                _required_text(
                    self.funding_source,
                    field_name="funding_source",
                ),
            )
        for field_name in (
            "expected_portfolio_contribution",
            "opportunity_cost_return",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            object.__setattr__(self, field_name, round(float(value), 8))
        for field_name, minimum in (
            ("constraint_evidence", 1),
            ("implementation_blocks", 0),
            ("review_conditions", 1),
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


@dataclass(frozen=True, slots=True)
class CandidateSpecialistContext:
    candidate_identifier: str
    analysis_completed_at: datetime
    macro: MacroSpecialistContext
    market: MarketSpecialistContext
    portfolio: PortfolioSpecialistContext
    forecast: CrossAssetForecastSpecialistContext | None = None
    company: CompanyAnalysis | None = None
    asset_valuation: AssetValuationSpecialistContext | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_identifier",
            _required_text(
                self.candidate_identifier,
                field_name="candidate_identifier",
            ),
        )
        _aware(
            self.analysis_completed_at,
            field_name="analysis_completed_at",
        )
        if not isinstance(self.macro, MacroSpecialistContext):
            raise TypeError("macro must be MacroSpecialistContext")
        if not isinstance(self.market, MarketSpecialistContext):
            raise TypeError("market must be MarketSpecialistContext")
        if not isinstance(self.portfolio, PortfolioSpecialistContext):
            raise TypeError("portfolio must be PortfolioSpecialistContext")
        if self.forecast is not None and not isinstance(
            self.forecast,
            CrossAssetForecastSpecialistContext,
        ):
            raise TypeError(
                "forecast must be CrossAssetForecastSpecialistContext or None"
            )
        if self.company is not None and not isinstance(
            self.company,
            CompanyAnalysis,
        ):
            raise TypeError("company must be CompanyAnalysis or None")
        if self.asset_valuation is not None and not isinstance(
            self.asset_valuation,
            AssetValuationSpecialistContext,
        ):
            raise TypeError(
                "asset_valuation must be AssetValuationSpecialistContext or None"
            )
        dated_contexts = [self.macro, self.market, self.portfolio]
        if self.forecast is not None:
            dated_contexts.append(self.forecast)
        if any(
            item.as_of > self.analysis_completed_at
            for item in dated_contexts
        ):
            raise ValueError(
                "specialist contexts cannot be newer than completion time"
            )
        if self.company is not None and self.company.as_of > self.analysis_completed_at:
            raise ValueError(
                "company analysis cannot be newer than completion time"
            )
        if (
            self.asset_valuation is not None
            and self.asset_valuation.as_of > self.analysis_completed_at
        ):
            raise ValueError(
                "asset valuation analysis cannot be newer than completion time"
            )


@dataclass(frozen=True, slots=True)
class SpecialistGovernancePolicy:
    version: str = "specialist-governance.v2"
    minimum_evidence_score: float = 0.70
    minimum_evidence_dimension: float = 0.50
    maximum_market_data_age_hours: float = 24.0
    minimum_forecast_calibration_score: float = 0.55
    minimum_forecast_model_agreement: float = 0.50
    minimum_forecast_stability: float = 0.50
    minimum_forecast_horizon_alignment: float = 0.50
    forecast_materiality_threshold: float = 0.01

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        for field_name in (
            "minimum_evidence_score",
            "minimum_evidence_dimension",
            "minimum_forecast_calibration_score",
            "minimum_forecast_model_agreement",
            "minimum_forecast_stability",
            "minimum_forecast_horizon_alignment",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        if self.maximum_market_data_age_hours <= 0.0:
            raise ValueError(
                "maximum_market_data_age_hours must be positive"
            )
        if not 0.0 < self.forecast_materiality_threshold <= 1.0:
            raise ValueError(
                "forecast_materiality_threshold must be between 0 and 1"
            )


class IndependentSpecialistService:
    """Create six first-pass analyses without cross-specialist input."""

    def __init__(
        self,
        policy: SpecialistGovernancePolicy | None = None,
    ) -> None:
        self.policy = policy or SpecialistGovernancePolicy()

    def analyze(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> IndependentSpecialistPacket:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be CandidateDecisionRecord")
        if not isinstance(context, CandidateSpecialistContext):
            raise TypeError("context must be CandidateSpecialistContext")
        if candidate.identifier != context.candidate_identifier:
            raise ValueError("specialist context does not match candidate")
        if context.analysis_completed_at < candidate.as_of:
            raise ValueError(
                "specialist completion cannot predate candidate evidence"
            )
        analyses = (
            self._macro(candidate, context),
            self._market(candidate, context),
            self._forecast(candidate, context),
            self._fundamental(candidate, context),
            self._portfolio(candidate, context),
            self._evidence(candidate, context),
        )
        return IndependentSpecialistPacket(
            candidate_identifier=candidate.identifier,
            analyses=analyses,
        )

    @staticmethod
    def _completed(
        context: CandidateSpecialistContext,
        offset: int,
    ) -> datetime:
        return context.analysis_completed_at + timedelta(microseconds=offset)

    def _macro(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> SpecialistAnalysis:
        macro = context.macro
        position = _position(macro.expected_return_impact)
        support = macro.tailwinds or (
            f"Macro regime is {macro.regime}",
        )
        risks = tuple(dict.fromkeys(macro.headwinds + macro.systemic_risks))
        return SpecialistAnalysis(
            candidate_identifier=candidate.identifier,
            role=SpecialistRole.MACRO_ECONOMIC,
            completed_at=self._completed(context, 1),
            independent_first_pass=True,
            position=position,
            conclusion=(
                f"The {macro.regime} regime has an estimated "
                f"{macro.expected_return_impact:+.2%} effect on the opportunity."
            ),
            expected_return_impact=macro.expected_return_impact,
            confidence=macro.confidence,
            supporting_evidence=support,
            contradictory_evidence=macro.headwinds,
            critical_assumptions=(
                "The current macro regime classification remains valid",
            ),
            risks=risks,
            limitations=(
                "Macro relationships may change across regimes",
            ),
            change_conditions=macro.scenarios,
            evidence_origin_identifiers=macro.evidence_identifiers,
        )

    def _market(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> SpecialistAnalysis:
        market = context.market
        position = _position(market.expected_return_impact)
        return SpecialistAnalysis(
            candidate_identifier=candidate.identifier,
            role=SpecialistRole.MARKET,
            completed_at=self._completed(context, 2),
            independent_first_pass=True,
            position=position,
            conclusion=(
                f"Price, participation, positioning, and liquidity in the "
                f"{market.market_regime} market regime imply an estimated "
                f"{market.expected_return_impact:+.2%} return effect."
            ),
            expected_return_impact=market.expected_return_impact,
            confidence=market.confidence,
            supporting_evidence=market.evidence,
            contradictory_evidence=tuple(
                item
                for item in market.risks
                if market.expected_return_impact >= 0.0
            ),
            critical_assumptions=(
                "Observed trend and positioning remain representative through implementation",
            ),
            risks=market.risks,
            limitations=(
                "Market behavior can reverse before fundamentals change",
            ),
            change_conditions=market.entry_conditions,
            evidence_origin_identifiers=(
                market.evidence_identifiers or market.evidence
            ),
        )

    def _forecast(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> SpecialistAnalysis:
        forecast = context.forecast
        if forecast is None:
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.CROSS_ASSET_FORECAST,
                completed_at=self._completed(context, 3),
                independent_first_pass=True,
                position=SpecialistPosition.ABSTAIN,
                conclusion=(
                    "No governed candidate-specific cross-asset forecast translation "
                    "was supplied."
                ),
                expected_return_impact=0.0,
                confidence=0.0,
                supporting_evidence=(
                    "Forecast evidence remains optional and cannot create a candidate",
                ),
                contradictory_evidence=(),
                critical_assumptions=(
                    "A complete scenario-to-candidate translation is required before "
                    "forecast evidence can influence CIO synthesis",
                ),
                risks=(
                    "The forward distribution was not independently validated by the "
                    "forecast specialist",
                ),
                limitations=(
                    "No specialist forecast packet was available",
                ),
                change_conditions=(
                    "Attach calibrated governed forecasts with complete candidate-specific "
                    "scenario mappings",
                ),
                evidence_origin_identifiers=candidate.evidence_identifiers,
            )

        quality_failures: list[str] = []
        if (
            forecast.calibration_score
            < self.policy.minimum_forecast_calibration_score
        ):
            quality_failures.append("forecast calibration is below threshold")
        if forecast.model_agreement < self.policy.minimum_forecast_model_agreement:
            quality_failures.append("forecast model agreement is below threshold")
        if forecast.forecast_stability < self.policy.minimum_forecast_stability:
            quality_failures.append("forecast stability is below threshold")
        horizon_alignment = forecast.horizon_alignment(
            candidate.decision_horizon_days
        )
        if (
            horizon_alignment
            < self.policy.minimum_forecast_horizon_alignment
        ):
            quality_failures.append(
                "forecast and candidate decision horizons are not sufficiently aligned"
            )

        confidence = min(
            forecast.aggregate_confidence,
            forecast.calibration_score,
            forecast.model_agreement,
            forecast.forecast_stability,
            horizon_alignment,
        )
        raw_impact = forecast.expected_return_impact
        applied_impact = 0.0 if quality_failures else raw_impact
        position = (
            SpecialistPosition.ABSTAIN
            if quality_failures
            else _position(
                applied_impact,
                threshold=self.policy.forecast_materiality_threshold,
            )
        )
        scenario_evidence = tuple(
            (
                f"{item.label}: probability={item.probability:.2%}, "
                f"candidate impact={item.candidate_return_impact:+.2%}, "
                f"path drawdown={item.expected_path_drawdown:.2%}"
            )
            for item in forecast.scenarios
        )
        adverse_scenarios = tuple(
            item.rationale
            for item in forecast.scenarios
            if item.candidate_return_impact < 0.0
        )
        conclusion = (
            "The governed cross-asset forecast distribution implies a "
            f"{raw_impact:+.2%} candidate return delta over "
            f"{forecast.forecast_horizon_days} days, with an expected path "
            f"drawdown of {forecast.expected_path_drawdown:.2%}."
        )
        if quality_failures:
            conclusion += " The specialist abstains because forecast quality gates failed."
        return SpecialistAnalysis(
            candidate_identifier=candidate.identifier,
            role=SpecialistRole.CROSS_ASSET_FORECAST,
            completed_at=self._completed(context, 3),
            independent_first_pass=True,
            position=position,
            conclusion=conclusion,
            expected_return_impact=applied_impact,
            confidence=confidence,
            supporting_evidence=tuple(
                dict.fromkeys(scenario_evidence + forecast.cross_asset_signals)
            ),
            contradictory_evidence=tuple(
                dict.fromkeys(
                    forecast.contradictory_evidence
                    + adverse_scenarios
                    + tuple(quality_failures)
                )
            ),
            critical_assumptions=(
                "Scenario-to-candidate return mappings remain valid through the "
                "decision horizon",
                "Forecast model dependencies and overlapping evidence remain disclosed",
            ),
            risks=(
                f"Probability of a material path drawdown is "
                f"{forecast.path_drawdown_probability:.2%}",
                *forecast.limitations,
            ),
            limitations=(
                "Forecasts estimate distributions and cannot guarantee the realized path",
                *forecast.limitations,
            ),
            change_conditions=forecast.change_conditions,
            evidence_origin_identifiers=forecast.evidence_identifiers,
        )

    def _fundamental(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> SpecialistAnalysis:
        company = context.company
        asset_valuation = context.asset_valuation
        equity_candidate = candidate.instrument.asset_class in {
            CandidateAssetClass.US_EQUITY,
            CandidateAssetClass.INTERNATIONAL_EQUITY,
        }
        if company is None and asset_valuation is not None:
            if asset_valuation.asset_class is not candidate.instrument.asset_class:
                raise ValueError("asset valuation class does not match candidate")
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.FUNDAMENTAL_VALUATION,
                completed_at=self._completed(context, 4),
                independent_first_pass=True,
                position=_position(asset_valuation.expected_return_impact),
                conclusion=(
                    "Independent asset-specific valuation and return-driver evidence was reviewed."
                ),
                expected_return_impact=asset_valuation.expected_return_impact,
                confidence=asset_valuation.confidence,
                supporting_evidence=asset_valuation.valuation_evidence,
                contradictory_evidence=asset_valuation.contradictory_evidence,
                critical_assumptions=asset_valuation.critical_assumptions,
                risks=asset_valuation.risks,
                limitations=asset_valuation.limitations,
                change_conditions=asset_valuation.change_conditions,
                evidence_origin_identifiers=asset_valuation.evidence_identifiers,
            )
        if company is None:
            requirement = (
                "point-in-time company quality and valuation analysis"
                if equity_candidate
                else "independent asset-specific valuation analysis"
            )
            return SpecialistAnalysis(
                candidate_identifier=candidate.identifier,
                role=SpecialistRole.FUNDAMENTAL_VALUATION,
                completed_at=self._completed(context, 4),
                independent_first_pass=True,
                position=SpecialistPosition.ABSTAIN,
                conclusion=f"Required {requirement} is unavailable.",
                expected_return_impact=0.0,
                confidence=0.0,
                supporting_evidence=(
                    "The candidate record discloses the missing independent valuation packet",
                ),
                contradictory_evidence=(),
                critical_assumptions=(
                    "Independent valuation evidence is required before a recommendation",
                ),
                risks=(
                    "The candidate return estimate cannot be independently verified",
                ),
                limitations=(
                    "No independent company or asset-specific valuation packet was supplied",
                ),
                change_conditions=(
                    "Provide point-in-time independent valuation and return-driver evidence",
                ),
                evidence_origin_identifiers=candidate.evidence_identifiers,
            )
        if company.symbol != candidate.instrument.symbol:
            raise ValueError("company analysis symbol does not match candidate")
        quality = company.factor(CompanyFactor.QUALITY)
        growth = company.factor(CompanyFactor.GROWTH)
        valuation = company.factor(CompanyFactor.VALUATION)
        earnings_quality = company.factor(CompanyFactor.EARNINGS_QUALITY)
        impact = (
            quality.score * 0.025
            + growth.score * 0.025
            + valuation.score * 0.035
            + earnings_quality.score * 0.015
        )
        confidence = min(
            company.confidence,
            quality.confidence,
            valuation.confidence,
        )
        return SpecialistAnalysis(
            candidate_identifier=candidate.identifier,
            role=SpecialistRole.FUNDAMENTAL_VALUATION,
            completed_at=self._completed(context, 4),
            independent_first_pass=True,
            position=_position(impact),
            conclusion=(
                f"Company quality, growth, earnings quality, and valuation "
                f"produce a {impact:+.2%} estimated return contribution."
            ),
            expected_return_impact=impact,
            confidence=confidence,
            supporting_evidence=tuple(
                item.evidence[0]
                for item in (quality, growth, earnings_quality, valuation)
            ),
            contradictory_evidence=tuple(
                item.risks[0]
                for item in (quality, growth, earnings_quality, valuation)
                if item.score < 0.35 or item.confidence < 0.75
            ),
            critical_assumptions=candidate.critical_assumptions,
            risks=tuple(
                dict.fromkeys(
                    risk
                    for item in (quality, growth, earnings_quality, valuation)
                    for risk in item.risks
                )
            ),
            limitations=(
                "Initial factor thresholds require walk-forward calibration",
            ),
            change_conditions=candidate.invalidation_conditions,
            evidence_origin_identifiers=tuple(
                dict.fromkeys(
                    item.evidence[0]
                    for item in (quality, growth, earnings_quality, valuation)
                )
            ),
        )

    def _portfolio(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> SpecialistAnalysis:
        portfolio = context.portfolio
        blocks = portfolio.implementation_blocks
        proposed = portfolio.proposed_position_weight
        if blocks:
            position = SpecialistPosition.OPPOSED
            impact = min(0.0, candidate.expected_portfolio_contribution)
        elif proposed is None or proposed <= 0.0:
            position = SpecialistPosition.ABSTAIN
            impact = 0.0
        else:
            position = _position(
                candidate.net_expected_return
                - portfolio.opportunity_cost_return
            )
            impact = portfolio.expected_portfolio_contribution
        return SpecialistAnalysis(
            candidate_identifier=candidate.identifier,
            role=SpecialistRole.PORTFOLIO_RISK,
            completed_at=self._completed(context, 5),
            independent_first_pass=True,
            position=position,
            conclusion=(
                "The candidate has a feasible portfolio ceiling and identified funding source; final sizing remains with the CIO after reconciliation."
                if proposed is not None and not blocks
                else "No fully feasible portfolio expression is currently available."
            ),
            expected_return_impact=impact,
            confidence=(
                candidate.evidence_quality.ceiling
                if proposed is not None and not blocks
                else 0.40
            ),
            supporting_evidence=portfolio.constraint_evidence,
            contradictory_evidence=blocks,
            critical_assumptions=(
                "Portfolio exposures and implementation costs remain current",
            ),
            risks=blocks
            or (
                "Portfolio contribution may differ from the point-in-time estimate",
            ),
            limitations=(
                "Construction remains a paper proposal and does not represent fills",
            ),
            change_conditions=portfolio.review_conditions,
            implementation_blocks=blocks,
            recommended_position_weight=proposed,
            funding_source=portfolio.funding_source,
        )

    def _evidence(
        self,
        candidate: CandidateDecisionRecord,
        context: CandidateSpecialistContext,
    ) -> SpecialistAnalysis:
        quality = candidate.evidence_quality
        vetoes: list[str] = []
        if (
            candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY
            and context.company is None
        ):
            vetoes.append(
                "point-in-time normalized company analysis is missing for a U.S. equity"
            )
        if quality.score < self.policy.minimum_evidence_score:
            vetoes.append("aggregate evidence quality is below governance threshold")
        if quality.ceiling < self.policy.minimum_evidence_dimension:
            vetoes.append("at least one evidence dimension is below governance threshold")
        if candidate.instrument.data_age_hours > self.policy.maximum_market_data_age_hours:
            vetoes.append("market evidence is stale")
        if not candidate.evidence_identifiers:
            vetoes.append("evidence identifiers are missing")
        if not candidate.model_versions:
            vetoes.append("model versions are missing")
        if candidate.review_at <= candidate.as_of:
            vetoes.append("review timing is not reproducible")
        position = (
            SpecialistPosition.OPPOSED
            if vetoes
            else SpecialistPosition.SUPPORTIVE
        )
        evidence = (
            f"reliability={quality.reliability:.3f}",
            f"freshness={quality.freshness:.3f}",
            f"relevance={quality.relevance:.3f}",
            f"independence={quality.independence:.3f}",
            f"completeness={quality.completeness:.3f}",
            f"point-in-time integrity={quality.point_in_time_integrity:.3f}",
        )
        return SpecialistAnalysis(
            candidate_identifier=candidate.identifier,
            role=SpecialistRole.EVIDENCE_GOVERNANCE,
            completed_at=self._completed(context, 6),
            independent_first_pass=True,
            position=position,
            conclusion=(
                "The candidate evidence is reproducible and satisfies governance requirements."
                if not vetoes
                else "The candidate evidence does not satisfy governance requirements."
            ),
            expected_return_impact=0.0,
            confidence=quality.ceiling,
            supporting_evidence=evidence,
            contradictory_evidence=candidate.contradictory_evidence,
            critical_assumptions=(
                "Evidence identifiers and model versions resolve to immutable records",
            ),
            risks=tuple(vetoes)
            or (
                "Evidence may be revised after the decision timestamp",
            ),
            limitations=(
                "Evidence confidence is capped by the weakest disclosed dimension",
            ),
            change_conditions=(
                "Refresh stale evidence",
                "Resolve source conflicts or missing coverage",
                "Recalculate after material data revisions",
            ),
            veto_reasons=tuple(vetoes),
            evidence_origin_identifiers=candidate.evidence_identifiers,
        )


__all__ = [
    "AssetValuationSpecialistContext",
    "CandidateSpecialistContext",
    "CrossAssetForecastSpecialistContext",
    "ForecastScenarioAssessment",
    "IndependentSpecialistService",
    "MacroSpecialistContext",
    "MarketSpecialistContext",
    "PortfolioSpecialistContext",
    "SpecialistGovernancePolicy",
]
