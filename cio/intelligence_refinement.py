"""Integrity refinements for the authoritative CIO synthesis path.

This layer preserves the existing CIO action architecture while closing four narrow
intelligence gaps: historical-learning confidence ceilings, specialist-reconciled
path drawdown risk, horizon-consistent alternative-edge metadata, and explicit
staged/joint-preview decision metadata. It does not add a committee seat, vote, veto,
execution authority, or live-money capability.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from math import isfinite
from typing import Iterator

from cio.committee_advisory_cio import ChiefInvestmentOfficer as _AdvisoryChiefInvestmentOfficer
from cio.models import CIOAction, CIODecision, CandidateDecisionRecord
from cio.robustness import RobustCandidateAssessor


_DECISION_CONTEXT_PREFIX = "decision-context.v1:"
_PATH_RISK_REASON = (
    "reconciled scenario path drawdown exceeds the applicable worst-case portfolio limit"
)
_STAGED_MARKER = "Portfolio-posture staged participation applies:"


class PathAwareRobustCandidateAssessor(RobustCandidateAssessor):
    """Apply reconciled intra-horizon drawdown to the existing robustness boundary."""

    def __init__(self, policy=None) -> None:
        super().__init__(policy)
        self._active_path_drawdowns: ContextVar[
            dict[str, tuple[tuple[str, float], ...]]
        ] = ContextVar(
            f"cio_path_drawdowns_{id(self)}",
            default={},
        )

    @contextmanager
    def bind_path_drawdowns(
        self,
        candidate_identifier: str,
        values: tuple[tuple[str, float], ...],
    ) -> Iterator[None]:
        if not isinstance(candidate_identifier, str) or not candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not isinstance(values, tuple):
            raise TypeError("path drawdowns must be a tuple")
        normalized: list[tuple[str, float]] = []
        for label, value in values:
            if not isinstance(label, str) or not label.strip():
                raise ValueError("path drawdown labels cannot be empty")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("path drawdown values must be numeric")
            number = float(value)
            if not isfinite(number) or not -1.0 <= number <= 0.0:
                raise ValueError("path drawdown values must be finite between -1 and 0")
            normalized.append((label.strip(), number))
        token = self._active_path_drawdowns.set(
            {candidate_identifier: tuple(normalized)}
        )
        try:
            yield
        finally:
            self._active_path_drawdowns.reset(token)

    def assess(
        self,
        candidate,
        *,
        alternative_return,
        position_weight=None,
        policy_profile=None,
    ):
        assessment = super().assess(
            candidate,
            alternative_return=alternative_return,
            position_weight=position_weight,
            policy_profile=policy_profile,
        )
        values = self._active_path_drawdowns.get().get(candidate.identifier, ())
        if not values:
            return assessment
        scenario_labels = {item.label for item in candidate.scenario_distribution}
        unknown = sorted({label for label, _ in values} - scenario_labels)
        if unknown:
            raise ValueError(
                f"reconciled path drawdowns reference unknown scenarios: {unknown}"
            )
        worst_asset_path = min(
            value - candidate.implementation_cost_return for _, value in values
        )
        path_portfolio_return = assessment.reference_position_weight * worst_asset_path
        worst_case = min(
            assessment.worst_case_portfolio_return,
            path_portfolio_return,
        )
        minimum_worst_case = (
            policy_profile.minimum_worst_case_portfolio_return
            if policy_profile is not None
            else self.policy.minimum_worst_case_portfolio_return
        )
        reasons = list(assessment.reasons)
        if worst_case < minimum_worst_case and _PATH_RISK_REASON not in reasons:
            reasons.append(_PATH_RISK_REASON)
        unique_reasons = tuple(dict.fromkeys(reasons))
        return replace(
            assessment,
            worst_case_portfolio_return=round(worst_case, 10),
            passed=not unique_reasons,
            reasons=unique_reasons,
        )


def cap_historical_confidence(confidence: float, specialists) -> float:
    """Apply the historical-learning ceiling after dependency-aware confidence."""

    ceiling = float(specialists.historical_learning.confidence_ceiling)
    return round(max(0.0, min(float(confidence), ceiling, 1.0)), 8)


def decision_stage(decision: CIODecision, candidate: CandidateDecisionRecord) -> tuple[str, str]:
    """Return machine-readable qualification stage and participation mode."""

    staged = (
        decision.action is CIOAction.BUY
        and candidate.current_portfolio_weight <= 0.0
        and _STAGED_MARKER in decision.rationale
    )
    if staged:
        return "exploratory", "portfolio_posture_staged"
    if decision.action in {CIOAction.BUY, CIOAction.INCREASE}:
        return "qualified", "standard"
    if candidate.current_portfolio_weight > 0.0:
        return "holding_review", "standard"
    return "review", "standard"


def refine_decision_context_payload(
    payload: dict[str, object],
    *,
    decision: CIODecision,
    candidate: CandidateDecisionRecord,
    joint_preview=None,
) -> dict[str, object]:
    """Correct explanatory metadata without changing the already-selected action."""

    resolved = dict(payload)
    reconciliation = decision.return_reconciliation
    horizon_alternative = (
        None
        if reconciliation is None
        else reconciliation.horizon_alternative_return
    )
    resolved["horizon_alternative_return"] = horizon_alternative
    resolved["best_alternative_relative_edge"] = (
        None
        if horizon_alternative is None
        else round(decision.expected_return - horizon_alternative, 8)
    )
    # Keep the legacy key for readers already consuming it, but make the quantity
    # horizon-consistent. The best-alternative field above is the preferred semantic name.
    resolved["cash_relative_edge"] = resolved["best_alternative_relative_edge"]
    stage, participation_mode = decision_stage(decision, candidate)
    resolved["decision_stage"] = stage
    resolved["participation_mode"] = participation_mode
    if reconciliation is not None:
        resolved["reconciled_path_drawdown_by_scenario"] = {
            label: value for label, value in reconciliation.path_drawdown_by_scenario
        }
        resolved["path_drawdown_is_robustness_authoritative"] = bool(
            reconciliation.path_drawdown_by_scenario
        )

    action_ladder = resolved.get("action_ladder")
    if isinstance(action_ladder, dict):
        ladder = dict(action_ladder)
        reduce_block = ladder.get("reduce")
        if isinstance(reduce_block, dict):
            reduce_copy = dict(reduce_block)
            triggers = list(reduce_copy.get("triggers", ()))
            triggers.append(
                "thesis contradiction or evidence-integrity emergency reduces unsupported exposure"
            )
            reduce_copy["triggers"] = list(dict.fromkeys(str(item) for item in triggers))
            ladder["reduce"] = reduce_copy
        exit_block = ladder.get("exit")
        if isinstance(exit_block, dict):
            exit_copy = dict(exit_block)
            triggers = [
                str(item)
                for item in exit_copy.get("triggers", ())
                if str(item) != "complete thesis invalidation or integrity emergency"
            ]
            triggers.append(
                "a governed reduction target that resolves to zero is normalized to exit"
            )
            exit_copy["triggers"] = list(dict.fromkeys(triggers))
            ladder["exit"] = exit_copy
        resolved["action_ladder"] = ladder

    if joint_preview is not None:
        requested = joint_preview.requested_for(candidate.identifier)
        target = joint_preview.target_for(candidate.identifier)
        resolved["joint_portfolio_preview"] = {
            "identifier": joint_preview.identifier,
            "status": joint_preview.status,
            "policy_version": joint_preview.policy_version,
            "requested_target": requested,
            "simultaneous_target": target,
            "positive_cap": joint_preview.positive_cap_for(
                candidate.identifier,
                current_weight=candidate.current_portfolio_weight,
            ),
            "target_cash_weight": joint_preview.target_cash_weight,
            "expected_return_improvement": joint_preview.expected_return_improvement,
            "blocks": list(joint_preview.blocks),
            "final_construction_authority": False,
        }
    return resolved


def refine_decision_context(
    decision: CIODecision,
    candidate: CandidateDecisionRecord,
    *,
    joint_preview=None,
) -> CIODecision:
    monitoring: list[str] = []
    found = False
    for item in decision.monitoring_indicators:
        if not item.startswith(_DECISION_CONTEXT_PREFIX):
            monitoring.append(item)
            continue
        found = True
        payload = json.loads(item[len(_DECISION_CONTEXT_PREFIX) :])
        if not isinstance(payload, dict):
            raise ValueError("decision context payload must be an object")
        refined = refine_decision_context_payload(
            payload,
            decision=decision,
            candidate=candidate,
            joint_preview=joint_preview,
        )
        monitoring.append(
            _DECISION_CONTEXT_PREFIX
            + json.dumps(
                refined,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    if not found:
        return decision
    return replace(decision, monitoring_indicators=tuple(monitoring))


class ChiefInvestmentOfficer(_AdvisoryChiefInvestmentOfficer):
    """Canonical CIO with path-aware robustness and integrity-consistent metadata."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.robust_assessor = PathAwareRobustCandidateAssessor(
            self.robust_assessor.policy
        )

    def _confidence(
        self,
        candidate,
        *,
        specialists,
        has_dissent,
        reconciliation,
    ) -> float:
        confidence = super()._confidence(
            candidate,
            specialists=specialists,
            has_dissent=has_dissent,
            reconciliation=reconciliation,
        )
        return cap_historical_confidence(confidence, specialists)

    def synthesize(
        self,
        candidate,
        universe,
        specialists,
        *,
        capital_comparison=None,
        prior_context=None,
        analysis_lane: str = "acquisition",
    ) -> CIODecision:
        effective_alternative = (
            candidate.opportunity_cost_return
            if capital_comparison is None
            else capital_comparison.effective_opportunity_cost
        )
        reconciliation = self.reconciler.reconcile(
            candidate,
            specialists,
            alternative_return=effective_alternative,
        )
        with self.robust_assessor.bind_path_drawdowns(
            candidate.identifier,
            reconciliation.path_drawdown_by_scenario,
        ):
            decision = super().synthesize(
                candidate,
                universe,
                specialists,
                capital_comparison=capital_comparison,
                prior_context=prior_context,
                analysis_lane=analysis_lane,
            )
        return refine_decision_context(
            decision,
            candidate,
            joint_preview=getattr(self, "joint_portfolio_preview", None),
        )


__all__ = [
    "ChiefInvestmentOfficer",
    "PathAwareRobustCandidateAssessor",
    "cap_historical_confidence",
    "decision_stage",
    "refine_decision_context",
    "refine_decision_context_payload",
]
