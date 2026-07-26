"""Canonical end-to-end Capital Intelligence CIO decision cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cio import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    ChiefInvestmentOfficer,
    IndependentSpecialistPacket,
)
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from committee.specialists import (
    CandidateSpecialistContext,
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
)
from portfolio.construction_api import (
    ConstructionIntent,
    ConstructionStatus,
    PortfolioAsset,
    PortfolioConstructionEngine,
    PortfolioConstructionPolicy,
    PortfolioConstructionRequest,
    PortfolioConstructionResult,
    TradeSide,
)
from reporting.daily_cio import DailyCIOBriefing, DailyCIOBriefingBuilder
from thesis import LivingThesis


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
    ) -> PortfolioConstructionRequest:
        return PortfolioConstructionRequest(
            identifier=identifier,
            as_of=self.as_of,
            portfolio_value=self.portfolio_value,
            cash_weight=self.cash_weight,
            cash_expected_return=self.cash_expected_return,
            positions=self.positions,
            intents=intents,
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
    company: CompanyAnalysis | None = None

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
        if self.company is not None and not isinstance(
            self.company,
            CompanyAnalysis,
        ):
            raise TypeError("company must be CompanyAnalysis or None")


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

    def run(
        self,
        *,
        identifier: str,
        candidates: tuple[CandidateDecisionRecord, ...],
        opportunity_context: OpportunitySetContext,
        specialist_contexts: tuple[CandidateCycleContext, ...],
        portfolio: CyclePortfolioState,
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
        context_map = {
            item.candidate_identifier: item for item in specialist_contexts
        }
        if len(context_map) != len(specialist_contexts):
            raise ValueError("specialist candidate contexts must be unique")

        queue = self.opportunity_engine.build_queue(
            candidates,
            opportunity_context,
        )
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
            )
            specialist_context = CandidateSpecialistContext(
                candidate_identifier=candidate.identifier,
                analysis_completed_at=base_context.analysis_completed_at,
                macro=base_context.macro,
                market=base_context.market,
                portfolio=portfolio_context,
                company=base_context.company,
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
    ) -> PortfolioSpecialistContext:
        profile = portfolio.profile(candidate.identifier)
        current_weight = portfolio.current_weight(
            candidate.instrument.symbol
        )
        if abs(current_weight - candidate.current_portfolio_weight) > 0.000001:
            raise ValueError(
                "candidate current weight does not match portfolio state"
            )
        action = (
            CIOAction.INCREASE if current_weight > 0.0 else CIOAction.BUY
        )
        intent = ConstructionIntent(
            candidate_identifier=candidate.identifier,
            symbol=candidate.instrument.symbol,
            action=action,
            requested_target_weight=candidate.maximum_position_weight,
            expected_return=candidate.net_expected_return,
            opportunity_edge=candidate.opportunity_edge,
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
            if target_weight > current_weight + 0.000001
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
                else candidate.net_expected_return
                * (proposed - current_weight)
            ),
            opportunity_cost_return=(
                candidate.opportunity_cost_return
            ),
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
        portfolio: CyclePortfolioState,
    ) -> PortfolioConstructionResult | None:
        intents: list[ConstructionIntent] = []
        for decision in decisions:
            if decision.action not in _ACTIONABLE:
                continue
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
                    priority_rank=ranked.rank,
                )
            )
        if not intents:
            return None
        return self.construction_engine.construct(
            portfolio.request(
                identifier=f"construction:{cycle_identifier}",
                intents=tuple(intents),
            )
        )

    def _create_theses(
        self,
        *,
        decisions: tuple[CIODecision, ...],
        ranked_by_candidate: dict[str, object],
        construction: PortfolioConstructionResult | None,
        portfolio: CyclePortfolioState,
        code_version: str | None,
    ) -> tuple[LivingThesis, ...]:
        target_weights = (
            {} if construction is None else dict(construction.target_weights)
        )
        theses: list[LivingThesis] = []
        for decision in decisions:
            if decision.action not in _OWNERSHIP:
                continue
            ranked = ranked_by_candidate[decision.candidate_identifier]
            candidate = ranked.candidate
            current = portfolio.current_weight(candidate.instrument.symbol)
            if decision.action in {CIOAction.BUY, CIOAction.INCREASE}:
                if construction is None or construction.status is ConstructionStatus.BLOCKED:
                    continue
                if target_weights.get(candidate.instrument.symbol, 0.0) <= current + 0.000001:
                    continue
            elif decision.action is CIOAction.HOLD and current <= 0.0:
                continue
            thesis = LivingThesis.from_decision(candidate, decision)
            theses.append(thesis)
            if self.journal is not None:
                self.journal.append_thesis_snapshot(
                    thesis,
                    code_version=code_version,
                )
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