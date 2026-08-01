"""Canonical end-to-end Capital Intelligence CIO decision cycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from cio import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    ChiefInvestmentOfficer,
    HistoricalLearningContext,
    HistoricalLearningResolver,
    IndependentSpecialistPacket,
    PriorDecisionContext,
)
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from committee.specialists import (
    AssetValuationSpecialistContext,
    CandidateSpecialistContext,
    CrossAssetForecastSpecialistContext,
    IndependentSpecialistService,
    MacroSpecialistContext,
    MarketSpecialistContext,
    PortfolioSpecialistContext,
)
from company import CompanyAnalysis
from evaluation import DecisionEvidenceSnapshot
from evaluation.persistence import append_construction, append_evidence_snapshot
from opportunity import (
    OpportunityEngine,
    OpportunityQueue,
    OpportunitySetContext,
    OpportunityRankingInput,
)
from portfolio.construction_api import (
    ConstructionIntent,
    ConstructionMode,
    ConstructionStatus,
    PortfolioAsset,
    PortfolioConstructionEngine,
    PortfolioConstructionPolicy,
    PortfolioConstructionRequest,
    PortfolioConstructionResult,
    PortfolioScenario,
    TradeSide,
)
from portfolio.derivative_lifecycle import DerivativeLifecycleProfile
from portfolio.scenario_authority import (
    GovernedPortfolioScenarioSet,
    PortfolioScenarioAuthority,
)
from reporting.daily_cio import DailyCIOBriefing, DailyCIOBriefingBuilder
from thesis import (
    LivingThesis,
    StructuredThesisConditionScorer,
    ThesisCondition,
)


_ACTIONABLE = {
    CIOAction.BUY,
    CIOAction.INCREASE,
    CIOAction.REDUCE,
    CIOAction.EXIT,
}
_OWNERSHIP = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.HOLD}


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


def _loading_tuple(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, tuple):
        raise TypeError("factor_loadings must be a tuple")
    normalized: list[tuple[str, float]] = []
    for name, loading in value:
        label = _required_text(name, field_name="factor name")
        if isinstance(loading, bool) or not isinstance(loading, (int, float)):
            raise TypeError("factor loading must be numeric")
        number = float(loading)
        if not -1.0 <= number <= 1.0:
            raise ValueError("factor loading must be between -1 and 1")
        normalized.append((label, round(number, 8)))
    if len(normalized) != len({name for name, _ in normalized}):
        raise ValueError("factor loading names must be unique")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class CandidateExposureProfile:
    """Portfolio metadata required for preview and final construction."""

    candidate_identifier: str
    sector: str
    factor_loadings: tuple[tuple[str, float], ...]
    correlation_bucket: str
    thesis_conditions: tuple[ThesisCondition, ...] = ()
    invalidation_conditions_structured: tuple[ThesisCondition, ...] = ()
    derivative_lifecycle: DerivativeLifecycleProfile | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_identifier",
            "sector",
            "correlation_bucket",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "factor_loadings",
            _loading_tuple(self.factor_loadings),
        )
        for field_name in (
            "thesis_conditions",
            "invalidation_conditions_structured",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, ThesisCondition) for item in values
            ):
                raise TypeError(f"{field_name} must contain ThesisCondition values")
        if self.derivative_lifecycle is not None and not isinstance(
            self.derivative_lifecycle, DerivativeLifecycleProfile
        ):
            raise TypeError(
                "derivative_lifecycle must be DerivativeLifecycleProfile or None"
            )


@dataclass(frozen=True, slots=True)
class CyclePortfolioState:
    """One point-in-time portfolio used for previews and final construction."""

    identifier: str
    as_of: datetime
    portfolio_value: float
    cash_weight: float
    cash_expected_return: float
    positions: tuple[PortfolioAsset, ...]
    exposure_profiles: tuple[CandidateExposureProfile, ...]
    eligible_universe_publication_identifier: str | None = None
    scenario_set: GovernedPortfolioScenarioSet | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "portfolio_value",
            "cash_weight",
            "cash_expected_return",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            object.__setattr__(self, field_name, round(float(value), 8))
        if self.portfolio_value <= 0.0:
            raise ValueError("portfolio_value must be positive")
        if not 0.0 <= self.cash_weight <= 1.0:
            raise ValueError("cash_weight must be between 0 and 1")
        if not isinstance(self.positions, tuple) or not all(
            isinstance(item, PortfolioAsset) for item in self.positions
        ):
            raise TypeError("positions must contain PortfolioAsset values")
        if not isinstance(self.exposure_profiles, tuple) or not all(
            isinstance(item, CandidateExposureProfile)
            for item in self.exposure_profiles
        ):
            raise TypeError(
                "exposure_profiles must contain CandidateExposureProfile values"
            )
        profiles = tuple(
            item.candidate_identifier for item in self.exposure_profiles
        )
        if len(profiles) != len(set(profiles)):
            raise ValueError("candidate exposure profiles must be unique")
        if abs(
            sum(item.current_weight for item in self.positions)
            + self.cash_weight
            - 1.0
        ) > 0.000001:
            raise ValueError("portfolio positions and cash must sum to 1.0")
        if self.scenario_set is not None:
            if not isinstance(self.scenario_set, GovernedPortfolioScenarioSet):
                raise TypeError("scenario_set must be GovernedPortfolioScenarioSet or None")
            if self.scenario_set.as_of > self.as_of:
                raise ValueError("portfolio scenario set cannot be from the future")
        if self.eligible_universe_publication_identifier is not None:
            object.__setattr__(
                self,
                "eligible_universe_publication_identifier",
                _required_text(
                    self.eligible_universe_publication_identifier,
                    field_name="eligible_universe_publication_identifier",
                ),
            )

    def profile(self, candidate_identifier: str) -> CandidateExposureProfile:
        resolved = _required_text(
            candidate_identifier,
            field_name="candidate_identifier",
        )
        return next(
            (
                item
                for item in self.exposure_profiles
                if item.candidate_identifier == resolved
            ),
            None,
        ) or (_raise_missing_profile(resolved))

    def current_weight(self, symbol: str) -> float:
        resolved = symbol.strip().upper()
        return next(
            (
                item.current_weight
                for item in self.positions
                if item.symbol == resolved
            ),
            0.0,
        )

    def request(
        self,
        *,
        identifier: str,
        intents: tuple[ConstructionIntent, ...],
        scenarios: tuple[PortfolioScenario, ...] = (),
        mode: ConstructionMode = ConstructionMode.NORMAL,
    ) -> PortfolioConstructionRequest:
        scenario_identifier = None
        if not scenarios and self.scenario_set is not None:
            symbols = tuple(
                sorted(
                    {item.symbol for item in self.positions}
                    | {item.symbol for item in intents}
                )
            )
            scenarios = PortfolioScenarioAuthority().authorize(
                self.scenario_set,
                as_of=self.as_of,
                symbols=symbols,
            )
            scenario_identifier = self.scenario_set.identifier
        return PortfolioConstructionRequest(
            identifier=identifier,
            as_of=self.as_of,
            portfolio_value=self.portfolio_value,
            cash_weight=self.cash_weight,
            cash_expected_return=self.cash_expected_return,
            positions=self.positions,
            intents=intents,
            eligible_universe_publication_identifier=(
                self.eligible_universe_publication_identifier
            ),
            scenarios=scenarios,
            mode=mode,
            scenario_set_identifier=scenario_identifier,
        )


def _raise_missing_profile(candidate_identifier: str):
    raise KeyError(
        f"missing exposure profile for {candidate_identifier}"
    )


@dataclass(frozen=True, slots=True)
class CandidateCycleContext:
    """Independent evidence contexts supplied for one qualified candidate."""

    candidate_identifier: str
    analysis_completed_at: datetime
    macro: MacroSpecialistContext
    market: MarketSpecialistContext
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


@dataclass(frozen=True, slots=True)
class CanonicalCIOCycleResult:
    """Complete immutable result of one governed decision cycle."""

    identifier: str
    as_of: datetime
    opportunity_queue: OpportunityQueue
    decisions: tuple[CIODecision, ...]
    construction: PortfolioConstructionResult | None
    theses: tuple[LivingThesis, ...]
    evaluation_snapshots: tuple[DecisionEvidenceSnapshot, ...]
    briefing: DailyCIOBriefing

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.opportunity_queue, OpportunityQueue):
            raise TypeError("opportunity_queue must be OpportunityQueue")
        if not isinstance(self.decisions, tuple) or not all(
            isinstance(item, CIODecision) for item in self.decisions
        ):
            raise TypeError("decisions must contain CIODecision values")
        if self.construction is not None and not isinstance(
            self.construction,
            PortfolioConstructionResult,
        ):
            raise TypeError(
                "construction must be PortfolioConstructionResult or None"
            )
        if not isinstance(self.theses, tuple) or not all(
            isinstance(item, LivingThesis) for item in self.theses
        ):
            raise TypeError("theses must contain LivingThesis values")
        if not isinstance(self.evaluation_snapshots, tuple) or not all(
            isinstance(item, DecisionEvidenceSnapshot)
            for item in self.evaluation_snapshots
        ):
            raise TypeError(
                "evaluation_snapshots must contain DecisionEvidenceSnapshot values"
            )
        if len(self.evaluation_snapshots) != len(self.decisions):
            raise ValueError(
                "each CIO decision must have one point-in-time evaluation snapshot"
            )
        if not isinstance(self.briefing, DailyCIOBriefing):
            raise TypeError("briefing must be DailyCIOBriefing")
        if self.briefing.as_of != self.as_of:
            raise ValueError("briefing must share cycle timestamp")


class CanonicalCIOCycle:
    """Run opportunity, specialists, CIO, construction, thesis, and reporting."""

    def __init__(
        self,
        *,
        opportunity_engine: OpportunityEngine | None = None,
        specialist_service: IndependentSpecialistService | None = None,
        cio: ChiefInvestmentOfficer | None = None,
        construction_engine: PortfolioConstructionEngine | None = None,
        construction_policy: PortfolioConstructionPolicy | None = None,
        briefing_builder: DailyCIOBriefingBuilder | None = None,
        journal: SQLiteCIOJournal | None = None,
        historical_learning_resolver: HistoricalLearningResolver | None = None,
    ) -> None:
        self.opportunity_engine = opportunity_engine or OpportunityEngine()
        self.specialist_service = (
            specialist_service or IndependentSpecialistService()
        )
        self.cio = cio or ChiefInvestmentOfficer()
        self.construction_engine = construction_engine or PortfolioConstructionEngine(
            construction_policy
        )
        self.briefing_builder = briefing_builder or DailyCIOBriefingBuilder()
        self.journal = journal
        self.historical_learning_resolver = (
            historical_learning_resolver or HistoricalLearningResolver.from_environment()
        )

    def run(
        self,
        *,
        identifier: str,
        candidates: tuple[CandidateDecisionRecord, ...],
        opportunity_context: OpportunitySetContext,
        specialist_contexts: tuple[CandidateCycleContext, ...],
        portfolio: CyclePortfolioState,
        prior_decision_contexts: tuple[PriorDecisionContext, ...] = (),
        active_theses: tuple[LivingThesis, ...] = (),
        authoritative_opportunity_queue: OpportunityQueue | None = None,
        code_version: str | None = None,
    ) -> CanonicalCIOCycleResult:
        cycle_identifier = _required_text(identifier, field_name="identifier")
        if not isinstance(candidates, tuple) or not all(
            isinstance(item, CandidateDecisionRecord) for item in candidates
        ):
            raise TypeError(
                "candidates must contain CandidateDecisionRecord values"
            )
        if not isinstance(opportunity_context, OpportunitySetContext):
            raise TypeError(
                "opportunity_context must be OpportunitySetContext"
            )
        if not isinstance(specialist_contexts, tuple) or not all(
            isinstance(item, CandidateCycleContext)
            for item in specialist_contexts
        ):
            raise TypeError(
                "specialist_contexts must contain CandidateCycleContext values"
            )
        if not isinstance(portfolio, CyclePortfolioState):
            raise TypeError("portfolio must be CyclePortfolioState")
        if opportunity_context.as_of != portfolio.as_of:
            raise ValueError(
                "opportunity context and portfolio must share cycle timestamp"
            )
        if any(item.as_of != portfolio.as_of for item in candidates):
            raise ValueError("all candidates must share cycle timestamp")
        if not isinstance(prior_decision_contexts, tuple) or not all(
            isinstance(item, PriorDecisionContext)
            for item in prior_decision_contexts
        ):
            raise TypeError(
                "prior_decision_contexts must contain PriorDecisionContext values"
            )
        prior_map = {item.candidate_identifier: item for item in prior_decision_contexts}
        if not isinstance(active_theses, tuple) or not all(
            isinstance(item, LivingThesis) for item in active_theses
        ):
            raise TypeError("active_theses must contain LivingThesis values")
        if len(prior_map) != len(prior_decision_contexts):
            raise ValueError("prior decision contexts must be unique by candidate")
        if authoritative_opportunity_queue is None:
            generated_ranking = self._ranking_inputs(
                candidates,
                portfolio,
                minimum_cash_weight=(
                    self.construction_engine.policy.minimum_cash_weight
                ),
            )
            supplied_ranking = {
                item.candidate_identifier: item
                for item in opportunity_context.ranking_inputs
            }
            supplied_ranking.update(
                {
                    item.candidate_identifier: item
                    for item in generated_ranking
                    if item.candidate_identifier not in supplied_ranking
                }
            )
            opportunity_context = replace(
                opportunity_context,
                ranking_inputs=tuple(supplied_ranking.values()),
            )
            queue = self.opportunity_engine.build_queue(
                candidates,
                opportunity_context,
            )
        else:
            if not isinstance(authoritative_opportunity_queue, OpportunityQueue):
                raise TypeError(
                    "authoritative_opportunity_queue must be OpportunityQueue or None"
                )
            if (
                authoritative_opportunity_queue.context_identifier
                != opportunity_context.identifier
            ):
                raise ValueError(
                    "authoritative opportunity queue does not match the context"
                )
            represented = {
                *(
                    item.candidate.identifier
                    for item in authoritative_opportunity_queue.ranked
                ),
                *(
                    item.candidate_identifier
                    for item in authoritative_opportunity_queue.rejected
                ),
            }
            if represented != {item.identifier for item in candidates}:
                raise ValueError(
                    "authoritative opportunity queue candidate coverage is invalid"
                )
            queue = authoritative_opportunity_queue
        context_map = {
            item.candidate_identifier: item for item in specialist_contexts
        }
        if len(context_map) != len(specialist_contexts):
            raise ValueError("specialist candidate contexts must be unique")
        self._journal_candidates_and_queue(
            candidates=candidates,
            queue=queue,
            as_of=portfolio.as_of,
            code_version=code_version,
        )

        decisions: list[CIODecision] = []
        packets_by_candidate: dict[str, IndependentSpecialistPacket] = {}
        ranked_by_candidate = {
            item.candidate.identifier: item for item in queue.ranked
        }
        for ranked in queue.ranked:
            candidate = ranked.candidate
            base_context = context_map.get(candidate.identifier)
            if base_context is None:
                raise KeyError(
                    f"missing specialist context for {candidate.identifier}"
                )
            portfolio_context = self._preview_portfolio(
                candidate=candidate,
                rank=ranked.rank,
                portfolio=portfolio,
                effective_opportunity_cost=(
                    ranked.qualification.effective_opportunity_cost
                ),
            )
            if cycle_identifier.startswith("historical-canonical-cycle:"):
                historical_learning = HistoricalLearningContext.not_applicable(
                    candidate_identifier=candidate.identifier,
                    as_of=base_context.analysis_completed_at,
                    reason=(
                        "Historical replay cannot consume a manifest generated from its "
                        "own future results."
                    ),
                )
            else:
                historical_learning = self.historical_learning_resolver.resolve(
                    candidate,
                    as_of=base_context.analysis_completed_at,
                    macro_regime=base_context.macro.regime,
                    market_regime=base_context.market.market_regime,
                )
            specialist_context = CandidateSpecialistContext(
                candidate_identifier=candidate.identifier,
                analysis_completed_at=base_context.analysis_completed_at,
                macro=base_context.macro,
                market=base_context.market,
                portfolio=portfolio_context,
                forecast=base_context.forecast,
                company=base_context.company,
                asset_valuation=base_context.asset_valuation,
                historical_learning=historical_learning,
            )
            packet = self.specialist_service.analyze(
                candidate,
                specialist_context,
            )
            packets_by_candidate[candidate.identifier] = packet
            decision = self.cio.synthesize(
                candidate,
                ranked.qualification.universe,
                packet,
                capital_comparison=ranked.qualification.capital_comparison,
                prior_context=prior_map.get(candidate.identifier),
                analysis_lane=ranked.qualification.analysis_lane.value,
            )
            decisions.append(decision)
            if self.journal is not None:
                completed_at = max(
                    item.completed_at for item in packet.analyses
                )
                self.journal.append_specialist_packet(
                    packet,
                    occurred_at=completed_at,
                    code_version=code_version,
                )
                self.journal.append_decision(
                    decision,
                    code_version=code_version,
                )

        construction = self._construct_final_portfolio(
            cycle_identifier=cycle_identifier,
            decisions=tuple(decisions),
            ranked_by_candidate=ranked_by_candidate,
            packets_by_candidate=packets_by_candidate,
            portfolio=portfolio,
        )
        if self.journal is not None and construction is not None:
            append_construction(
                self.journal,
                construction,
                code_version=code_version or "unknown",
            )
        theses = self._create_theses(
            decisions=tuple(decisions),
            ranked_by_candidate=ranked_by_candidate,
            construction=construction,
            portfolio=portfolio,
            active_theses=active_theses,
            code_version=code_version,
        )
        snapshots = self._capture_evaluation_snapshots(
            decisions=tuple(decisions),
            ranked_by_candidate=ranked_by_candidate,
            packets_by_candidate=packets_by_candidate,
            opportunity_context=opportunity_context,
            construction=construction,
            theses=theses,
            code_version=code_version or "unknown",
        )
        briefing = self.briefing_builder.build(
            as_of=portfolio.as_of,
            queue=queue,
            decisions=tuple(decisions),
            construction=construction,
            theses=theses,
        )
        if self.journal is not None:
            self.journal.append(
                event_type=CIOJournalEventType.DAILY_CIO_BRIEFING,
                aggregate_identifier=cycle_identifier,
                occurred_at=portfolio.as_of,
                payload={
                    **briefing.to_dict(),
                    "cycle_identifier": cycle_identifier,
                    "code_version": code_version or "unknown",
                },
                schema_version="daily-cio-briefing.v1",
                event_identifier=f"event:daily-cio:{cycle_identifier}",
            )
        return CanonicalCIOCycleResult(
            identifier=cycle_identifier,
            as_of=portfolio.as_of,
            opportunity_queue=queue,
            decisions=tuple(decisions),
            construction=construction,
            theses=theses,
            evaluation_snapshots=snapshots,
            briefing=briefing,
        )


    @classmethod
    def prepare_ranking_inputs(
        cls,
        candidates: tuple[CandidateDecisionRecord, ...],
        portfolio: CyclePortfolioState,
        *,
        minimum_cash_weight: float = 0.02,
    ) -> tuple[OpportunityRankingInput, ...]:
        """Return the exact portfolio-aware inputs frozen before CIO review."""
        return cls._ranking_inputs(
            candidates,
            portfolio,
            minimum_cash_weight=minimum_cash_weight,
        )

    @classmethod
    def _ranking_inputs(
        cls,
        candidates: tuple[CandidateDecisionRecord, ...],
        portfolio: CyclePortfolioState,
        *,
        minimum_cash_weight: float = 0.02,
    ) -> tuple[OpportunityRankingInput, ...]:
        sector_weights: dict[str, float] = {}
        bucket_weights: dict[str, float] = {}
        for asset in portfolio.positions:
            sector_weights[asset.sector] = (
                sector_weights.get(asset.sector, 0.0) + asset.current_weight
            )
            bucket_weights[asset.correlation_bucket] = (
                bucket_weights.get(asset.correlation_bucket, 0.0)
                + asset.current_weight
            )
        values: list[OpportunityRankingInput] = []
        for candidate in candidates:
            try:
                profile = portfolio.profile(candidate.identifier)
                profile_sector = profile.sector
                profile_bucket = profile.correlation_bucket
                thesis_conditions = profile.thesis_conditions
                invalidation_conditions_structured = (
                    profile.invalidation_conditions_structured
                )
            except KeyError:
                profile_sector = "unclassified"
                profile_bucket = "unclassified"
                thesis_conditions = ()
                invalidation_conditions_structured = ()
            current = portfolio.current_weight(candidate.instrument.symbol)
            feasible_delta = max(
                0.0,
                min(
                    candidate.maximum_position_weight - current,
                    max(0.0, portfolio.cash_weight - minimum_cash_weight),
                ),
            )
            annualized = ConstructionIntent.annualized_return(
                candidate.net_expected_return,
                horizon_days=candidate.decision_horizon_days,
            )
            transition_cost = candidate.implementation_cost_return * feasible_delta
            contribution = (
                (annualized - portfolio.cash_expected_return) * feasible_delta
                - transition_cost
            )
            concentration = max(
                sector_weights.get(profile_sector, 0.0),
                bucket_weights.get(profile_bucket, 0.0),
            )
            diversification = max(0.0, min(1.0, 1.0 - concentration))
            scorer = StructuredThesisConditionScorer()
            thesis = scorer.score(thesis_conditions).score
            invalidation = scorer.score(
                invalidation_conditions_structured
            ).score
            horizon_factor = min(
                1.0, max(0.20, candidate.decision_horizon_days / 90.0)
            )
            durability = max(
                0.0,
                min(
                    1.0,
                    horizon_factor
                    * (
                        0.50 * candidate.evidence_quality.freshness
                        + 0.30 * candidate.evidence_quality.completeness
                        + 0.20 * candidate.evidence_quality.independence
                    ),
                ),
            )
            values.append(
                OpportunityRankingInput(
                    candidate_identifier=candidate.identifier,
                    marginal_portfolio_contribution=contribution,
                    diversification_score=diversification,
                    thesis_clarity_score=thesis,
                    invalidation_clarity_score=invalidation,
                    forecast_durability_score=durability,
                )
            )
        return tuple(values)

    def _capture_evaluation_snapshots(
        self,
        *,
        decisions: tuple[CIODecision, ...],
        ranked_by_candidate: dict[str, object],
        packets_by_candidate: dict[str, IndependentSpecialistPacket],
        opportunity_context: OpportunitySetContext,
        construction: PortfolioConstructionResult | None,
        theses: tuple[LivingThesis, ...],
        code_version: str,
    ) -> tuple[DecisionEvidenceSnapshot, ...]:
        thesis_by_decision = {
            item.decision_identifier: item for item in theses
        }
        snapshots: list[DecisionEvidenceSnapshot] = []
        for decision in decisions:
            ranked = ranked_by_candidate[decision.candidate_identifier]
            packet = packets_by_candidate[decision.candidate_identifier]
            captured_at = max(
                item.completed_at for item in packet.analyses
            )
            snapshot = DecisionEvidenceSnapshot.capture(
                candidate=ranked.candidate,
                ranked=ranked,
                decision=decision,
                packet=packet,
                opportunity_context=opportunity_context,
                construction=construction,
                thesis=thesis_by_decision.get(decision.identifier),
                captured_at=captured_at,
                code_version=code_version,
            )
            snapshots.append(snapshot)
            if self.journal is not None:
                append_evidence_snapshot(self.journal, snapshot)
        return tuple(snapshots)

    def _preview_portfolio(
        self,
        *,
        candidate: CandidateDecisionRecord,
        rank: int,
        portfolio: CyclePortfolioState,
        effective_opportunity_cost: float,
    ) -> PortfolioSpecialistContext:
        profile = portfolio.profile(candidate.identifier)
        current_weight = portfolio.current_weight(
            candidate.instrument.symbol
        )
        if abs(current_weight - candidate.current_portfolio_weight) > 0.000001:
            raise ValueError(
                "candidate current weight does not match portfolio state"
            )
        annualized_return = ConstructionIntent.annualized_return(
            candidate.net_expected_return,
            horizon_days=candidate.decision_horizon_days,
        )
        if current_weight > 0.0 and candidate.net_expected_return <= -0.05:
            action = CIOAction.EXIT
            requested_target_weight = 0.0
        elif current_weight > 0.0 and candidate.net_expected_return < 0.0:
            action = CIOAction.REDUCE
            requested_target_weight = round(current_weight / 2.0, 8)
        else:
            action = CIOAction.INCREASE if current_weight > 0.0 else CIOAction.BUY
            # This preview establishes only a feasible ceiling and exact funding
            # source. Final sizing occurs after specialist return reconciliation.
            requested_target_weight = candidate.maximum_position_weight
        intent = ConstructionIntent(
            candidate_identifier=candidate.identifier,
            symbol=candidate.instrument.symbol,
            action=action,
            requested_target_weight=requested_target_weight,
            expected_return=annualized_return,
            opportunity_edge=round(
                annualized_return - effective_opportunity_cost,
                8,
            ),
            maximum_position_weight=candidate.maximum_position_weight,
            sector=profile.sector,
            factor_loadings=profile.factor_loadings,
            correlation_bucket=profile.correlation_bucket,
            average_daily_dollar_volume=(
                candidate.instrument.average_daily_dollar_volume
            ),
            transaction_cost_bps=candidate.transaction_cost_bps,
            slippage_bps=candidate.slippage_bps,
            priority_rank=rank,
            instrument_identifier=candidate.instrument.instrument_id,
        )
        preview = self.construction_engine.construct(
            portfolio.request(
                identifier=f"preview:{candidate.identifier}",
                intents=(intent,),
            )
        )
        target_weight = dict(preview.target_weights).get(
            candidate.instrument.symbol,
            0.0,
        )
        proposed = (
            target_weight
            if abs(target_weight - current_weight) > 0.000001
            else None
        )
        funding_symbols = tuple(
            item.symbol
            for item in preview.trades
            if item.side is TradeSide.SELL
            and candidate.instrument.symbol in item.funding_for
        )
        funding_source = (
            "cash above minimum reserve"
            if proposed is not None and not funding_symbols
            else (
                "reduce " + ", ".join(funding_symbols)
                if funding_symbols
                else None
            )
        )
        hard_blocks = (
            preview.blocks
            if proposed is None
            or preview.status is ConstructionStatus.BLOCKED
            else ()
        )
        evidence = tuple(
            item.detail for item in preview.constraints if item.satisfied
        ) or ("Portfolio constraints were evaluated",)
        review_conditions = tuple(
            dict.fromkeys(
                preview.blocks
                + (
                    "Re-run construction when portfolio weights, costs, liquidity, or exposures change",
                )
            )
        )
        return PortfolioSpecialistContext(
            as_of=portfolio.as_of,
            proposed_position_weight=proposed,
            funding_source=funding_source,
            expected_portfolio_contribution=(
                0.0
                if proposed is None
                else annualized_return
                * (proposed - current_weight)
            ),
            opportunity_cost_return=effective_opportunity_cost,
            constraint_evidence=evidence,
            implementation_blocks=hard_blocks,
            review_conditions=review_conditions,
        )

    def _construct_final_portfolio(
        self,
        *,
        cycle_identifier: str,
        decisions: tuple[CIODecision, ...],
        ranked_by_candidate: dict[str, object],
        packets_by_candidate: dict[str, IndependentSpecialistPacket],
        portfolio: CyclePortfolioState,
    ) -> PortfolioConstructionResult | None:
        actionable = tuple(
            decision for decision in decisions if decision.action in _ACTIONABLE
        )
        ordered = sorted(
            actionable,
            key=lambda decision: (
                0
                if decision.action in {CIOAction.EXIT, CIOAction.REDUCE}
                else 1,
                -packets_by_candidate[
                    decision.candidate_identifier
                ].portfolio_recommendation.expected_return_impact,
                ranked_by_candidate[decision.candidate_identifier].rank,
            ),
        )
        intents: list[ConstructionIntent] = []
        for priority_rank, decision in enumerate(ordered, start=1):
            ranked = ranked_by_candidate[decision.candidate_identifier]
            candidate = ranked.candidate
            profile = portfolio.profile(candidate.identifier)
            intents.append(
                ConstructionIntent.from_cio(
                    candidate,
                    decision,
                    sector=profile.sector,
                    factor_loadings=profile.factor_loadings,
                    correlation_bucket=profile.correlation_bucket,
                    priority_rank=priority_rank,
                    derivative_lifecycle=profile.derivative_lifecycle,
                )
            )
        if not intents:
            return None
        mode = (
            ConstructionMode.EMERGENCY_DE_RISKING
            if any(
                item.action in {CIOAction.REDUCE, CIOAction.EXIT}
                and (item.evidence_vetoes or item.expected_return <= -0.05)
                for item in decisions
            )
            else ConstructionMode.NORMAL
        )
        return self.construction_engine.construct(
            portfolio.request(
                identifier=f"construction:{cycle_identifier}",
                intents=tuple(intents),
                mode=mode,
            )
        )

    def _create_theses(
        self,
        *,
        decisions: tuple[CIODecision, ...],
        ranked_by_candidate: dict[str, object],
        construction: PortfolioConstructionResult | None,
        portfolio: CyclePortfolioState,
        active_theses: tuple[LivingThesis, ...],
        code_version: str | None,
    ) -> tuple[LivingThesis, ...]:
        target_weights = {} if construction is None else dict(construction.target_weights)
        existing_by_asset = {item.asset: item for item in active_theses}
        theses: list[LivingThesis] = []
        for decision in decisions:
            ranked = ranked_by_candidate[decision.candidate_identifier]
            candidate = ranked.candidate
            symbol = candidate.instrument.symbol
            current = portfolio.current_weight(symbol)
            implemented = target_weights.get(symbol, current)
            existing = existing_by_asset.get(symbol)
            thesis: LivingThesis | None = None
            if existing is None:
                if (
                    decision.action in {CIOAction.BUY, CIOAction.INCREASE}
                    and implemented > current + 0.000001
                ) or (
                    current > 0.000001
                    and decision.action is CIOAction.HOLD
                ):
                    # A pre-existing canonical holding may enter this decision epoch
                    # without a reconstructable thesis. A deferred HOLD must create
                    # one immutable continuity thesis before evaluation is captured.
                    thesis = LivingThesis.from_decision(candidate, decision)
            else:
                if decision.action is CIOAction.EXIT and implemented > 0.000001:
                    continue
                if decision.action is CIOAction.REDUCE and implemented >= current - 0.000001:
                    continue
                if decision.action in {
                    CIOAction.BUY,
                    CIOAction.INCREASE,
                    CIOAction.HOLD,
                    CIOAction.REDUCE,
                    CIOAction.EXIT,
                    CIOAction.NO_MATERIAL_CHANGE,
                }:
                    thesis = existing.continue_from_decision(candidate, decision)
            if thesis is None:
                continue
            theses.append(thesis)
            if self.journal is not None:
                self.journal.append_thesis_snapshot(thesis, code_version=code_version)
        return tuple(theses)

    def _journal_candidates_and_queue(
        self,
        *,
        candidates: tuple[CandidateDecisionRecord, ...],
        queue: OpportunityQueue,
        as_of: datetime,
        code_version: str | None,
    ) -> None:
        if self.journal is None:
            return
        for candidate in candidates:
            self.journal.append_candidate(
                candidate,
                code_version=code_version,
            )
        self.journal.append_opportunity_queue(
            queue,
            occurred_at=as_of,
            code_version=code_version,
        )


__all__ = [
    "CandidateCycleContext",
    "CandidateExposureProfile",
    "CanonicalCIOCycle",
    "CanonicalCIOCycleResult",
    "CyclePortfolioState",
]
