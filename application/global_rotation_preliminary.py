"""Pre-final-CIO global conviction assessment for simultaneous portfolio preview.

This module intentionally duplicates the deterministic reconciliation/robustness inputs
used by the canonical CIO so all six specialist packets can be considered together
before final candidate-by-candidate CIO synthesis. It has no action, construction, or
execution authority and never writes canonical CIO persistence.
"""
from __future__ import annotations

from contextlib import nullcontext

from portfolio.global_rotation import GlobalConvictionDecision


def assess_preliminary_global_conviction(
    cio,
    *,
    candidate,
    ranked,
    specialists,
    directive=None,
) -> GlobalConvictionDecision | None:
    """Return a non-authoritative stage/target using the final CIO's own economics."""

    context = getattr(cio, "global_rotation_context", None)
    policy = getattr(cio, "global_conviction_policy", None)
    if context is None or policy is None:
        return None

    profile = cio.policy_authority.resolve(candidate)
    effective_alternative = ranked.qualification.effective_opportunity_cost
    reconciliation = cio.reconciler.reconcile(
        candidate,
        specialists,
        alternative_return=effective_alternative,
    )
    robustness_candidate = cio._robustness_candidate(candidate, reconciliation)
    portfolio_cap = specialists.portfolio_recommendation.recommended_position_weight
    assessment_cap = (
        min(
            portfolio_cap,
            candidate.maximum_position_weight,
            profile.maximum_position_weight,
        )
        if portfolio_cap is not None and portfolio_cap > 0.0
        else (
            candidate.current_portfolio_weight
            if candidate.current_portfolio_weight > 0.0
            else min(candidate.maximum_position_weight, profile.maximum_position_weight)
        )
    )
    assessment_cap = round(assessment_cap, 8)

    binder = getattr(cio.robust_assessor, "bind_path_drawdowns", None)
    path_context = (
        binder(candidate.identifier, reconciliation.path_drawdown_by_scenario)
        if callable(binder)
        else nullcontext()
    )
    with path_context:
        supported_weight = cio.robust_assessor.maximum_supported_weight(
            robustness_candidate,
            alternative_return=effective_alternative,
            maximum_weight=assessment_cap,
            policy_profile=profile,
            allow_soft_failures=False,
        )
        assessment_weight = (
            supported_weight
            if supported_weight > 0.0
            else min(
                cio.robust_assessor.policy.minimum_reference_weight,
                assessment_cap,
            )
        )
        robustness = cio.robust_assessor.assess(
            robustness_candidate,
            alternative_return=effective_alternative,
            position_weight=assessment_weight,
            policy_profile=profile,
        )

    ensemble = cio.growth_ensemble.assess(
        candidate,
        specialists,
        robustness,
        profile,
        analysis_lane=ranked.qualification.analysis_lane.value,
    )
    return policy.assess(
        candidate=candidate,
        signal=context.by_candidate.get(candidate.identifier),
        universe=ranked.qualification.universe,
        specialists=specialists,
        robustness=robustness,
        reconciliation=reconciliation,
        profile=profile,
        ensemble=ensemble,
        directive=directive,
        material_opposition_threshold=cio.policy.maximum_unresolved_dissent_confidence,
    )


__all__ = ["assess_preliminary_global_conviction"]
