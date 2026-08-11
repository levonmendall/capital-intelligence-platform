"""Production canonical cycle for global opportunity rotation.

The cycle enriches already-governed candidates with mispriced-change and corroborated
global-leadership economics, propagates explicitly modeled structural-theme successor
attention, freezes the authoritative opportunity queue, performs a non-authoritative
all-candidate six-specialist preliminary pass for joint portfolio preview, and then
reuses those immutable packets in the unchanged final CIO/construction authority path.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from application.compounding_cycle import (
    CompoundingCanonicalCIOCycle,
    CompoundingCanonicalCIOCycleResult,
)
from application.global_rotation_preliminary import (
    PrecomputedSpecialistService,
    assess_preliminary_global_conviction,
)
from application.global_rotation_preview import build_global_rotation_preview
from cio import HistoricalLearningContext
from cio.global_rotation_authority import GlobalRotationChiefInvestmentOfficer
from cio.policy_authority import CanonicalDecisionPolicyAuthority
from committee.specialists import CandidateSpecialistContext
from intelligence.global_leadership import enrich_bundle_with_global_leadership_economics
from intelligence.mispriced_change import enrich_bundle_with_mispriced_change
from intelligence.theme_successor import propagate_theme_successors
from portfolio.global_rotation import GlobalRotationContext, build_global_rotation_context
from portfolio.global_rotation_persistence import (
    GlobalCashAccountability,
    SQLiteGlobalRotationStore,
    build_global_cash_accountability,
)

_LOGGER = logging.getLogger("capital_intelligence.global_rotation")


def enrich_global_rotation_contexts(
    contexts: tuple[object, ...],
    candidates: tuple[object, ...],
) -> tuple[object, ...]:
    """Build mispricing, theme-successor, then leadership context without guessing."""

    if not isinstance(contexts, tuple):
        raise TypeError("specialist_contexts must be supplied as a tuple")
    if not isinstance(candidates, tuple):
        raise TypeError("candidates must be supplied as a tuple")
    mispriced: list[object] = []
    for context in contexts:
        bundle = getattr(context, "forward_intelligence", None)
        if bundle is None:
            mispriced.append(context)
            continue
        mispriced.append(
            replace(
                context,
                forward_intelligence=enrich_bundle_with_mispriced_change(bundle),
            )
        )
    propagated = propagate_theme_successors(
        contexts=tuple(mispriced),
        candidates=candidates,
    )
    result: list[object] = []
    for context in propagated:
        bundle = getattr(context, "forward_intelligence", None)
        if bundle is None:
            result.append(context)
            continue
        result.append(
            replace(
                context,
                forward_intelligence=enrich_bundle_with_global_leadership_economics(
                    bundle
                ),
            )
        )
    return tuple(result)


class GlobalOpportunityRotationCanonicalCIOCycleResult(CompoundingCanonicalCIOCycleResult):
    """Canonical compounding result plus global rotation/cash accountability."""

    __slots__ = ("global_rotation_context", "global_cash_accountability")

    def __init__(
        self,
        *,
        base_result: CompoundingCanonicalCIOCycleResult,
        global_rotation_context: GlobalRotationContext,
        global_cash_accountability: GlobalCashAccountability,
    ) -> None:
        if not isinstance(base_result, CompoundingCanonicalCIOCycleResult):
            raise TypeError("base_result must be CompoundingCanonicalCIOCycleResult")
        if not isinstance(global_rotation_context, GlobalRotationContext):
            raise TypeError("global_rotation_context must be GlobalRotationContext")
        if not isinstance(global_cash_accountability, GlobalCashAccountability):
            raise TypeError("global_cash_accountability must be GlobalCashAccountability")
        super().__init__(
            base_result=base_result,
            portfolio_posture=base_result.portfolio_posture,
            view_expressions=base_result.view_expressions,
            portfolio_alternatives=base_result.portfolio_alternatives,
            position_lifecycle=base_result.position_lifecycle,
            reactive_monitoring=base_result.reactive_monitoring,
            compounding_accountability=base_result.compounding_accountability,
            advanced_intelligence_shadow=base_result.advanced_intelligence_shadow,
        )
        object.__setattr__(self, "global_rotation_context", global_rotation_context)
        object.__setattr__(
            self,
            "global_cash_accountability",
            global_cash_accountability,
        )


class GlobalOpportunityRotationCanonicalCIOCycle(CompoundingCanonicalCIOCycle):
    """Run the six-specialist/CIO process with global marginal-capital context."""

    def __init__(
        self,
        *,
        cio=None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
        global_rotation_store: SQLiteGlobalRotationStore | None = None,
        **kwargs,
    ) -> None:
        opportunity_engine = kwargs.get("opportunity_engine")
        authority = (
            policy_authority
            or getattr(cio, "policy_authority", None)
            or getattr(opportunity_engine, "policy_authority", None)
            or CanonicalDecisionPolicyAuthority()
        )
        resolved_cio = cio or GlobalRotationChiefInvestmentOfficer(
            policy_authority=authority
        )
        super().__init__(
            cio=resolved_cio,
            policy_authority=authority,
            **kwargs,
        )
        if not isinstance(self.specialist_service, PrecomputedSpecialistService):
            self.specialist_service = PrecomputedSpecialistService(
                self.specialist_service
            )
        self.global_rotation_store = global_rotation_store
        if self.global_rotation_store is None and self.journal is not None:
            self.global_rotation_store = SQLiteGlobalRotationStore(self.journal.path)

    def _freeze_authoritative_queue(self, *, kwargs, candidates, portfolio):
        """Use the same qualification inputs as the canonical cycle before rotation."""

        supplied_queue = kwargs.get("authoritative_opportunity_queue")
        if supplied_queue is not None:
            return dict(kwargs), supplied_queue
        opportunity_context = kwargs.get("opportunity_context")
        if opportunity_context is None:
            return dict(kwargs), None
        generated_ranking = self._ranking_inputs(
            candidates,
            portfolio,
            minimum_cash_weight=self.construction_engine.policy.minimum_cash_weight,
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
        frozen_context = replace(
            opportunity_context,
            ranking_inputs=tuple(supplied_ranking.values()),
        )
        queue = self.opportunity_engine.build_queue(candidates, frozen_context)
        return (
            {
                **kwargs,
                "opportunity_context": frozen_context,
                "authoritative_opportunity_queue": queue,
            },
            queue,
        )

    @staticmethod
    def _rotation_candidates(candidates, queue):
        """Return governed reviewed candidates with the true queue opportunity cost."""

        if queue is None:
            return candidates
        return tuple(
            replace(
                item.candidate,
                opportunity_cost_return=item.qualification.effective_opportunity_cost,
            )
            for item in tuple(getattr(queue, "ranked", ()) or ())
        )

    def _preliminary_specialist_packets(
        self,
        *,
        cycle_identifier: str,
        queue,
        specialist_contexts,
        portfolio,
        opportunity_context,
    ) -> dict[str, object]:
        """Build every six-specialist packet before any final CIO synthesis.

        This pass is non-persistent and non-authoritative. The exact immutable packets
        are reused by the base cycle, which persists them once in its normal order. This
        avoids doubling specialist work across a potentially large all-market set.
        """

        if queue is None or not tuple(getattr(queue, "ranked", ()) or ()):
            return {}
        context_map = {
            item.candidate_identifier: item for item in specialist_contexts
        }
        if len(context_map) != len(specialist_contexts):
            raise ValueError("specialist candidate contexts must be unique")
        ranked_values = tuple(queue.ranked)
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
                alternative_return=ranked.qualification.effective_opportunity_cost,
                invalidation_clarity=(
                    0.50
                    if opportunity_context.ranking_input(ranked.candidate.identifier)
                    is None
                    else opportunity_context.ranking_input(
                        ranked.candidate.identifier
                    ).invalidation_clarity_score
                ),
            )
            for ranked in ranked_values
        )
        risk_by_candidate = {
            item.candidate_identifier: item for item in risk_assessments
        }
        joint_assessments = self.joint_candidate_engine.assess(
            tuple(item.candidate for item in ranked_values),
            risk_assessments,
            tuple(
                portfolio.profile(item.candidate.identifier)
                for item in ranked_values
            ),
        )
        joint_by_candidate: dict[str, list[object]] = {}
        for item in joint_assessments:
            joint_by_candidate.setdefault(
                item.first_candidate_identifier, []
            ).append(item)
            joint_by_candidate.setdefault(
                item.second_candidate_identifier, []
            ).append(item)

        packets: dict[str, object] = {}
        for ranked in ranked_values:
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
            packets[candidate.identifier] = self.specialist_service.analyze(
                candidate,
                specialist_context,
            )
        return packets

    def _preliminary_conviction_targets(
        self,
        *,
        queue,
        packets,
    ) -> dict[str, float | None]:
        if queue is None:
            return {}
        targets: dict[str, float | None] = {}
        for ranked in tuple(getattr(queue, "ranked", ()) or ()):
            packet = packets.get(ranked.candidate.identifier)
            if packet is None:
                continue
            conviction = assess_preliminary_global_conviction(
                self.cio,
                candidate=ranked.candidate,
                ranked=ranked,
                specialists=packet,
            )
            if conviction is not None:
                targets[ranked.candidate.identifier] = conviction.target_weight
        return targets

    def run(self, **kwargs) -> GlobalOpportunityRotationCanonicalCIOCycleResult:
        contexts = kwargs.get("specialist_contexts")
        candidates = kwargs.get("candidates")
        portfolio = kwargs.get("portfolio")
        cycle_identifier = str(kwargs.get("identifier", "unknown"))
        code_version = str(kwargs.get("code_version") or "unknown")
        if not isinstance(contexts, tuple):
            raise TypeError("specialist_contexts must be supplied as a tuple")
        if not isinstance(candidates, tuple):
            raise TypeError("candidates must be supplied as a tuple")
        if portfolio is None:
            raise TypeError("portfolio must be supplied")

        enriched_contexts = enrich_global_rotation_contexts(contexts, candidates)
        prepared_kwargs, authoritative_queue = self._freeze_authoritative_queue(
            kwargs=kwargs,
            candidates=candidates,
            portfolio=portfolio,
        )
        reviewed_candidates = self._rotation_candidates(
            candidates,
            authoritative_queue,
        )
        rotation_context = build_global_rotation_context(
            candidates=reviewed_candidates,
            specialist_contexts=enriched_contexts,
            portfolio=portfolio,
            minimum_cash_weight=self.construction_engine.policy.minimum_cash_weight,
        )
        setter = getattr(self.cio, "set_global_rotation_context", None)
        clearer = getattr(self.cio, "clear_global_rotation_context", None)
        if callable(setter):
            setter(rotation_context)

        preliminary_packets: dict[str, object] = {}
        conviction_targets = None
        try:
            preliminary_packets = self._preliminary_specialist_packets(
                cycle_identifier=cycle_identifier,
                queue=authoritative_queue,
                specialist_contexts=enriched_contexts,
                portfolio=portfolio,
                opportunity_context=prepared_kwargs.get("opportunity_context"),
            )
            conviction_targets = self._preliminary_conviction_targets(
                queue=authoritative_queue,
                packets=preliminary_packets,
            )
        except Exception:
            # The preview must never become a hidden action veto. The canonical final
            # cycle below performs its own complete six-specialist analysis and fails
            # closed there if a required authoritative input is actually invalid.
            preliminary_packets = {}
            _LOGGER.exception(
                "specialist-informed global preview unavailable for %s; falling back to bounded leadership preview",
                cycle_identifier,
            )

        preview = None
        try:
            preview = build_global_rotation_preview(
                cycle_identifier=cycle_identifier,
                candidates=reviewed_candidates,
                portfolio=portfolio,
                construction_engine=self.construction_engine,
                rotation_context=rotation_context,
                authoritative_queue=authoritative_queue,
                conviction_targets=conviction_targets,
            )
        except Exception:
            _LOGGER.exception(
                "global joint portfolio preview unavailable for %s; continuing without pre-CIO cap",
                cycle_identifier,
            )
        preview_setter = getattr(self.cio, "set_joint_preview_context", None)
        preview_clearer = getattr(self.cio, "clear_joint_preview_context", None)
        if preview is not None and callable(preview_setter):
            preview_setter(preview)
        try:
            with self.specialist_service.bind_packets(preliminary_packets):
                base_result = super().run(
                    **{
                        **prepared_kwargs,
                        "specialist_contexts": enriched_contexts,
                    }
                )
            accountability = build_global_cash_accountability(
                cycle_identifier=cycle_identifier,
                context=rotation_context,
                result=base_result,
            )
            if self.global_rotation_store is not None:
                self.global_rotation_store.append(
                    cycle_identifier=cycle_identifier,
                    context=rotation_context,
                    accountability=accountability,
                    code_version=code_version,
                )
            return GlobalOpportunityRotationCanonicalCIOCycleResult(
                base_result=base_result,
                global_rotation_context=rotation_context,
                global_cash_accountability=accountability,
            )
        finally:
            if callable(preview_clearer):
                preview_clearer()
            if callable(clearer):
                clearer()


__all__ = [
    "GlobalOpportunityRotationCanonicalCIOCycle",
    "GlobalOpportunityRotationCanonicalCIOCycleResult",
    "enrich_global_rotation_contexts",
]
