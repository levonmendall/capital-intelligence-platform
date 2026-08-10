"""CIO authority for global opportunity rotation and graduated participation.

The CIO remains the sole investment-action authority. Global leadership/context can
change a soft abstention into a bounded exploratory/provisional position, or support
derisking a confirmed deteriorating holding. It cannot bypass hard evidence,
capability, implementation, downside, funding, or construction controls.
"""
from __future__ import annotations

import json
from dataclasses import replace

from cio.compounding_authority import CompoundingChiefInvestmentOfficer
from cio.models import CIOAction
from portfolio.global_rotation import (
    ConvictionStage,
    GlobalConvictionDecision,
    GlobalConvictionPolicy,
    GlobalRotationContext,
)

_DECISION_CONTEXT_PREFIX = "decision-context.v1:"
_GLOBAL_CONTEXT_PREFIX = "global-rotation-context.v1:"
_SOFT_ABSTENTIONS = {
    CIOAction.WATCH,
    CIOAction.NO_SUPERIOR_OPPORTUNITY,
    CIOAction.NO_MATERIAL_CHANGE,
}


class GlobalRotationChiefInvestmentOfficer(CompoundingChiefInvestmentOfficer):
    """Canonical CIO with global marginal-capital context."""

    def __init__(
        self,
        *args,
        global_conviction_policy: GlobalConvictionPolicy | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.global_conviction_policy = global_conviction_policy or GlobalConvictionPolicy()
        self._global_rotation_context: GlobalRotationContext | None = None
        self._global_convictions: dict[str, GlobalConvictionDecision] = {}

    @property
    def global_rotation_context(self) -> GlobalRotationContext | None:
        return self._global_rotation_context

    def set_global_rotation_context(self, context: GlobalRotationContext) -> None:
        if not isinstance(context, GlobalRotationContext):
            raise TypeError("context must be GlobalRotationContext")
        self._global_rotation_context = context
        self._global_convictions = {}

    def clear_global_rotation_context(self) -> None:
        self._global_rotation_context = None
        self._global_convictions = {}

    def _conviction(
        self,
        candidate,
        *,
        universe,
        specialists,
        robustness,
        reconciliation,
        profile,
        ensemble,
    ) -> GlobalConvictionDecision | None:
        context = self._global_rotation_context
        if context is None:
            return None
        decision = self.global_conviction_policy.assess(
            candidate=candidate,
            signal=context.by_candidate.get(candidate.identifier),
            universe=universe,
            specialists=specialists,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
            ensemble=ensemble,
            directive=self._allocation_directives.get(candidate.identifier),
            material_opposition_threshold=self.policy.maximum_unresolved_dissent_confidence,
        )
        self._global_convictions[candidate.identifier] = decision
        return decision

    def _apply_confirmed_deterioration(
        self,
        candidate,
        *,
        action: CIOAction,
        position_weight: float | None,
        reason: str,
        conviction: GlobalConvictionDecision | None,
    ) -> tuple[CIOAction, float | None, str]:
        context = self._global_rotation_context
        if context is None or float(candidate.current_portfolio_weight) <= 0.0:
            return action, position_weight, reason
        if conviction is not None and conviction.stage is ConvictionStage.BLOCKED:
            return action, position_weight, reason
        signal = context.by_candidate.get(candidate.identifier)
        if signal is None:
            return action, position_weight, reason
        confirmed = (
            signal.leadership_state == "deteriorating"
            and signal.mispriced_change_state in {"deteriorating", "value_trap_risk"}
        )
        if not confirmed:
            return action, position_weight, reason
        if action in {CIOAction.EXIT, CIOAction.REDUCE}:
            return action, position_weight, reason
        if action is CIOAction.INCREASE:
            action, position_weight = CIOAction.HOLD, None
        elif action in {CIOAction.HOLD, CIOAction.NO_MATERIAL_CHANGE}:
            current = float(candidate.current_portfolio_weight)
            action, position_weight = CIOAction.REDUCE, round(current / 2.0, 8)
        else:
            return action, position_weight, reason
        replacement = context.replacement_for(candidate.identifier)
        replacement_text = (
            ""
            if replacement is None
            else (
                f" Strongest cross-asset replacement is {replacement.candidate_identifier} "
                f"({replacement.domain.value}, global rank {replacement.rank}); it must independently clear CIO and construction controls."
            )
        )
        return (
            action,
            position_weight,
            reason
            + " Global rotation confirms deterioration in both market leadership and forward/mispriced economics, so unsupported equity or cross-asset exposure is reduced rather than waiting for a fully negative standalone forecast."
            + replacement_text,
        )

    def _select_action(
        self,
        candidate,
        *,
        universe,
        specialists,
        robustness,
        robustness_candidate,
        reconciliation,
        effective_alternative,
        profile,
        analysis_lane,
        ensemble,
        outage_assessment,
    ):
        action, position_weight, reason = super()._select_action(
            candidate,
            universe=universe,
            specialists=specialists,
            robustness=robustness,
            robustness_candidate=robustness_candidate,
            reconciliation=reconciliation,
            effective_alternative=effective_alternative,
            profile=profile,
            analysis_lane=analysis_lane,
            ensemble=ensemble,
            outage_assessment=outage_assessment,
        )
        conviction = self._conviction(
            candidate,
            universe=universe,
            specialists=specialists,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
            ensemble=ensemble,
        )
        action, position_weight, reason = self._apply_confirmed_deterioration(
            candidate,
            action=action,
            position_weight=position_weight,
            reason=reason,
            conviction=conviction,
        )
        if conviction is None:
            return action, position_weight, reason

        current = float(candidate.current_portfolio_weight)
        if (
            current <= 0.0
            and action in _SOFT_ABSTENTIONS
            and conviction.stage in {ConvictionStage.EXPLORATORY, ConvictionStage.PROVISIONAL}
            and conviction.authorized
        ):
            action = CIOAction.BUY
            position_weight = conviction.target_weight
            reason += (
                f" Global opportunity {conviction.stage.value} participation applies: "
                "hard controls passed and surviving positive economics are expressed through a bounded risk budget instead of automatic cash. "
                f"Target={position_weight:.2%}; final construction remains authoritative."
            )
        elif (
            action in {CIOAction.BUY, CIOAction.INCREASE}
            and position_weight is not None
            and conviction.stage in {ConvictionStage.EXPLORATORY, ConvictionStage.PROVISIONAL}
            and conviction.target_weight is not None
            and conviction.target_weight < float(position_weight)
        ):
            position_weight = conviction.target_weight
            reason += (
                f" Global conviction is {conviction.stage.value}, so ordinary uncertainty caps the positive target at {position_weight:.2%} instead of converting the opportunity to zero."
            )
        return self._apply_joint_preview_cap(
            candidate,
            action=action,
            position_weight=position_weight,
            reason=reason,
        )

    def _apply_hysteresis(
        self,
        candidate,
        *,
        action,
        position_weight,
        reason,
        prior_context,
        profile,
        progressive_lane,
        emergency,
    ):
        conviction = self._global_convictions.get(candidate.identifier)
        if (
            action is CIOAction.BUY
            and conviction is not None
            and conviction.stage in {ConvictionStage.EXPLORATORY, ConvictionStage.PROVISIONAL}
        ):
            progressive_lane = True
        return super()._apply_hysteresis(
            candidate,
            action=action,
            position_weight=position_weight,
            reason=reason,
            prior_context=prior_context,
            profile=profile,
            progressive_lane=progressive_lane,
            emergency=emergency,
        )

    @staticmethod
    def _rewrite_decision_stage(item: str, stage: ConvictionStage) -> str:
        if not item.startswith(_DECISION_CONTEXT_PREFIX):
            return item
        try:
            payload = json.loads(item[len(_DECISION_CONTEXT_PREFIX):])
        except (TypeError, ValueError, json.JSONDecodeError):
            return item
        if not isinstance(payload, dict):
            return item
        payload["decision_stage"] = stage.value
        payload["participation_mode"] = "global_opportunity_rotation"
        return _DECISION_CONTEXT_PREFIX + json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def synthesize(self, candidate, universe, specialists, **kwargs):
        decision = super().synthesize(candidate, universe, specialists, **kwargs)
        context = self._global_rotation_context
        conviction = self._global_convictions.get(candidate.identifier)
        if context is None or conviction is None:
            return decision
        signal = context.by_candidate.get(candidate.identifier)
        replacement = context.replacement_for(candidate.identifier)
        monitoring = [
            self._rewrite_decision_stage(item, conviction.stage)
            for item in decision.monitoring_indicators
        ]
        payload = {
            "policy_version": context.policy_version,
            "cash_competition_state": context.cash_competition_state.value,
            "minimum_cash_weight": context.minimum_cash_weight,
            "current_cash_weight": context.current_cash_weight,
            "excess_cash_weight": context.excess_cash_weight,
            "conviction_stage": conviction.stage.value,
            "conviction_target_weight": conviction.target_weight,
            "hard_blockers": list(conviction.hard_blockers),
            "soft_constraints": list(conviction.soft_constraints),
            "strongest_replacement_identifier": None if replacement is None else replacement.candidate_identifier,
            "investment_authority": False,
            "construction_authority": False,
        }
        if signal is not None:
            payload.update(
                {
                    "global_rank": signal.rank,
                    "global_score": signal.score,
                    "opportunity_domain": signal.domain.value,
                    "leadership_state": signal.leadership_state,
                    "leadership_score": signal.leadership_score,
                    "mispriced_change_state": signal.mispriced_change_state,
                    "mispriced_change_score": signal.mispriced_change_score,
                    "forward_impulse": signal.forward_impulse,
                    "pre_specialist_expected_return_edge": signal.expected_return_edge,
                }
            )
        monitoring.append(
            _GLOBAL_CONTEXT_PREFIX
            + json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
        return replace(decision, monitoring_indicators=tuple(dict.fromkeys(monitoring)))


__all__ = ["GlobalRotationChiefInvestmentOfficer"]
