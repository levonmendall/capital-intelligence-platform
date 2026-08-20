"""Bounded-memory production variant of the canonical CIO decision cycle.

The investment process is unchanged.  This variant changes only object lifetime:
production cycles with an append-only journal persist each complete specialist packet
immediately, retain only the scalar construction ordering input, and reconstruct one
packet at a time when the post-construction evidence snapshot is captured.

The class is composed into the existing compounding cycle with cooperative multiple
inheritance.  ``CompoundingCanonicalCIOCycle.run`` still owns the compounding layer;
its ``super().run`` resolves here before the historical ``CanonicalCIOCycle.run``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from application.bounded_specialist_packets import JournalBackedSpecialistPacketLoader
from application.cio_cycle import (
    CanonicalCIOCycle,
    CanonicalCIOCycleResult,
    _required_text,
)
from application.compounding_cycle import CompoundingCanonicalCIOCycle
from cio import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    HistoricalLearningContext,
    IndependentSpecialistPacket,
    PriorDecisionContext,
)
from cio.persistence import CIOJournalEventType
from committee.specialists import CandidateSpecialistContext
from evaluation import DecisionEvidenceSnapshot
from evaluation.persistence import append_construction, append_evidence_snapshot
from opportunity import OpportunityQueue, OpportunitySetContext
from portfolio.construction_api import reconcile_construction_decisions
from thesis import LivingThesis


@dataclass(frozen=True, slots=True)
class _PortfolioRecommendationSummary:
    expected_return_impact: float


@dataclass(frozen=True, slots=True)
class _PacketConstructionSummary:
    """Only specialist-packet field consumed by final construction ordering."""

    portfolio_recommendation: _PortfolioRecommendationSummary


class BoundedCanonicalCIOCycle(CanonicalCIOCycle):
    """Run the canonical cycle without retaining all full specialist packets."""

    def run(
        self,
        *,
        identifier: str,
        candidates: tuple[CandidateDecisionRecord, ...],
        opportunity_context: OpportunitySetContext,
        specialist_contexts: tuple[object, ...],
        portfolio,
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
        if not isinstance(specialist_contexts, tuple):
            raise TypeError("specialist_contexts must be supplied as a tuple")
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
        cycle_disposition = self.cycle_disposition_authority.decide(
            queue,
            as_of=portfolio.as_of,
        )
        self._journal_candidates_and_queue(
            candidates=candidates,
            queue=queue,
            as_of=portfolio.as_of,
            code_version=code_version,
        )

        decisions: list[CIODecision] = []
        packet_summaries: dict[str, _PacketConstructionSummary] = {}
        in_memory_packets: dict[str, IndependentSpecialistPacket] = {}
        packet_event_identifiers: dict[str, str] = {}
        ranked_by_candidate = {
            item.candidate.identifier: item for item in queue.ranked
        }
        risk_assessments = tuple(
            self.risk_intelligence_engine.assess(
                ranked.candidate,
                portfolio_value=portfolio.portfolio_value,
                proposed_weight=max(
                    portfolio.current_weight(ranked.candidate.instrument.symbol),
                    min(
                        ranked.candidate.maximum_position_weight,
                        portfolio.current_weight(ranked.candidate.instrument.symbol)
                        + max(
                            0.0,
                            portfolio.cash_weight
                            - self.construction_engine.policy.minimum_cash_weight,
                        ),
                    ),
                ),
                alternative_return=(
                    ranked.qualification.effective_opportunity_cost
                ),
                invalidation_clarity=(
                    0.50
                    if opportunity_context.ranking_input(
                        ranked.candidate.identifier
                    ) is None
                    else opportunity_context.ranking_input(
                        ranked.candidate.identifier
                    ).invalidation_clarity_score
                ),
            )
            for ranked in queue.ranked
        )
        risk_by_candidate = {
            item.candidate_identifier: item for item in risk_assessments
        }
        joint_candidate_assessments = self.joint_candidate_engine.assess(
            tuple(item.candidate for item in queue.ranked),
            risk_assessments,
            tuple(
                portfolio.profile(item.candidate.identifier)
                for item in queue.ranked
            ),
        )
        joint_by_candidate: dict[str, list[object]] = {}
        for item in joint_candidate_assessments:
            joint_by_candidate.setdefault(
                item.first_candidate_identifier, []
            ).append(item)
            joint_by_candidate.setdefault(
                item.second_candidate_identifier, []
            ).append(item)
        if self.journal is not None:
            for item in risk_assessments:
                self.journal.append(
                    event_type=CIOJournalEventType.CANDIDATE_RISK_ASSESSMENT,
                    aggregate_identifier=item.candidate_identifier,
                    occurred_at=portfolio.as_of,
                    payload={
                        **item.to_dict(),
                        "cycle_identifier": cycle_identifier,
                        "code_version": code_version or "unknown",
                    },
                    schema_version="candidate-risk-assessment.v1",
                    event_identifier=(
                        f"event:candidate-risk:{cycle_identifier}:{item.candidate_identifier}"
                    ),
                )
            for index, item in enumerate(joint_candidate_assessments, start=1):
                self.journal.append(
                    event_type=CIOJournalEventType.JOINT_CANDIDATE_ASSESSMENT,
                    aggregate_identifier=cycle_identifier,
                    occurred_at=portfolio.as_of,
                    payload={
                        **item.to_dict(),
                        "cycle_identifier": cycle_identifier,
                        "code_version": code_version or "unknown",
                    },
                    schema_version="joint-candidate-assessment.v1",
                    event_identifier=(
                        f"event:joint-candidate:{cycle_identifier}:{index}"
                    ),
                )
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
            candidate_risk = risk_by_candidate[candidate.identifier]
            pair_evidence = tuple(
                (
                    f"Joint candidate relation={item.relation.value}; "
                    f"tail dependence={item.tail_dependence:.0%}; "
                    f"{item.explanation}"
                )
                for item in joint_by_candidate.get(candidate.identifier, ())
            )
            portfolio_context = replace(
                portfolio_context,
                constraint_evidence=tuple(
                    dict.fromkeys(
                        portfolio_context.constraint_evidence
                        + candidate_risk.diagnostics
                        + pair_evidence
                    )
                ),
                implementation_blocks=tuple(
                    dict.fromkeys(
                        portfolio_context.implementation_blocks
                        + candidate_risk.hard_blocks
                    )
                ),
                review_conditions=tuple(
                    dict.fromkeys(
                        portfolio_context.review_conditions
                        + (
                            "Reassess candidate expected shortfall, conditional loss, recovery time, stress liquidity, thesis fragility, and joint portfolio relationships",
                        )
                    )
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
                forward_intelligence=base_context.forward_intelligence,
                historical_learning=historical_learning,
            )
            packet = self.specialist_service.analyze(
                candidate,
                specialist_context,
            )
            decision = self.cio.synthesize(
                candidate,
                ranked.qualification.universe,
                packet,
                capital_comparison=ranked.qualification.capital_comparison,
                prior_context=prior_map.get(candidate.identifier),
                analysis_lane=ranked.qualification.analysis_lane.value,
            )
            decisions.append(decision)
            packet_summaries[candidate.identifier] = _PacketConstructionSummary(
                portfolio_recommendation=_PortfolioRecommendationSummary(
                    expected_return_impact=(
                        packet.portfolio_recommendation.expected_return_impact
                    )
                )
            )
            if self.journal is not None:
                completed_at = max(
                    item.completed_at for item in packet.analyses
                )
                packet_event = self.journal.append_specialist_packet(
                    packet,
                    occurred_at=completed_at,
                    code_version=code_version,
                )
                packet_event_identifiers[candidate.identifier] = (
                    packet_event.event_identifier
                )
                self.journal.append_decision(
                    decision,
                    code_version=code_version,
                )
                del packet
            else:
                # Non-persistent rehearsal/test paths preserve historical in-memory
                # behavior. The production worker always supplies the append-only
                # journal and therefore uses the bounded path above.
                in_memory_packets[candidate.identifier] = packet

        construction = self._construct_final_portfolio(
            cycle_identifier=cycle_identifier,
            decisions=tuple(decisions),
            ranked_by_candidate=ranked_by_candidate,
            packets_by_candidate=packet_summaries,
            portfolio=portfolio,
        )
        if self.journal is not None and construction is not None:
            append_construction(
                self.journal,
                construction,
                code_version=code_version or "unknown",
            )
        construction_reconciliations = reconcile_construction_decisions(
            decisions=tuple(decisions),
            candidates=tuple(
                ranked_by_candidate[item.candidate_identifier].candidate
                for item in decisions
            ),
            construction=construction,
        )
        if self.journal is not None:
            for item in construction_reconciliations:
                self.journal.append(
                    event_type=(
                        CIOJournalEventType.CONSTRUCTION_RECONCILIATION
                    ),
                    aggregate_identifier=item.candidate_identifier,
                    occurred_at=portfolio.as_of,
                    payload={
                        **item.to_dict(),
                        "cycle_identifier": cycle_identifier,
                        "code_version": code_version or "unknown",
                    },
                    schema_version="construction-reconciliation.v1",
                    event_identifier=(
                        f"event:construction-reconciliation:{item.decision_identifier}"
                    ),
                )
        theses = self._create_theses(
            decisions=tuple(decisions),
            ranked_by_candidate=ranked_by_candidate,
            construction=construction,
            portfolio=portfolio,
            active_theses=active_theses,
            code_version=code_version,
        )
        if self.journal is not None:
            packet_loader = JournalBackedSpecialistPacketLoader(
                self.journal,
                packet_event_identifiers,
            ).load
        else:
            packet_loader = in_memory_packets.__getitem__
        snapshots = self._capture_bounded_evaluation_snapshots(
            decisions=tuple(decisions),
            ranked_by_candidate=ranked_by_candidate,
            packet_loader=packet_loader,
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
            cycle_disposition=cycle_disposition,
        )
        if self.journal is not None:
            self.journal.append(
                event_type=CIOJournalEventType.DAILY_CIO_BRIEFING,
                aggregate_identifier=cycle_identifier,
                occurred_at=portfolio.as_of,
                payload={
                    **briefing.to_dict(),
                    "cycle_identifier": cycle_identifier,
                    "cycle_disposition": (
                        None
                        if cycle_disposition is None
                        else cycle_disposition.to_dict()
                    ),
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
            construction_reconciliations=construction_reconciliations,
            risk_assessments=risk_assessments,
            joint_candidate_assessments=joint_candidate_assessments,
            theses=theses,
            evaluation_snapshots=snapshots,
            briefing=briefing,
            policy_authority_identifier=self.policy_authority.identifier,
            cycle_disposition=cycle_disposition,
        )

    def _capture_bounded_evaluation_snapshots(
        self,
        *,
        decisions: tuple[CIODecision, ...],
        ranked_by_candidate: dict[str, object],
        packet_loader,
        opportunity_context: OpportunitySetContext,
        construction,
        theses: tuple[LivingThesis, ...],
        code_version: str,
    ) -> tuple[DecisionEvidenceSnapshot, ...]:
        """Capture snapshots while materializing at most one full packet at a time."""

        thesis_by_decision = {
            item.decision_identifier: item for item in theses
        }
        snapshots: list[DecisionEvidenceSnapshot] = []
        for decision in decisions:
            ranked = ranked_by_candidate[decision.candidate_identifier]
            packet = packet_loader(decision.candidate_identifier)
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
            del packet
        return tuple(snapshots)


class BoundedCompoundingCanonicalCIOCycle(
    CompoundingCanonicalCIOCycle,
    BoundedCanonicalCIOCycle,
):
    """Compose the existing compounding layer over bounded canonical execution."""


__all__ = [
    "BoundedCanonicalCIOCycle",
    "BoundedCompoundingCanonicalCIOCycle",
]
