"""Pre-final-CIO global conviction assessment for simultaneous portfolio preview.

The global cycle computes all six-specialist packets before final CIO synthesis so the
joint portfolio preview is specialist-informed. Immutable specialist, candidate-risk,
and joint-candidate results are reused by the canonical final pass through context-local
memoization, avoiding duplicate all-market analysis and its memory cost. Nothing here
has action, construction, execution, or canonical persistence authority.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar, Token
from typing import Iterator

from portfolio.global_rotation import GlobalConvictionDecision


def _number_key(value: object) -> float:
    return round(float(value), 12)


class MemoizedCandidateRiskIntelligenceEngine:
    """Reuse deterministic candidate-risk assessments inside one rotation cycle."""

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self._active_cache: ContextVar[dict[tuple[object, ...], object] | None] = (
            ContextVar(
                f"global_rotation_candidate_risk_{id(self)}",
                default=None,
            )
        )

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def begin_cycle_cache(self) -> Token:
        return self._active_cache.set({})

    def end_cycle_cache(self, token: Token) -> None:
        self._active_cache.reset(token)

    def assess(
        self,
        candidate,
        *,
        portfolio_value,
        proposed_weight,
        alternative_return,
        invalidation_clarity=0.50,
    ):
        cache = self._active_cache.get()
        if cache is None:
            return self.delegate.assess(
                candidate,
                portfolio_value=portfolio_value,
                proposed_weight=proposed_weight,
                alternative_return=alternative_return,
                invalidation_clarity=invalidation_clarity,
            )
        key = (
            candidate.identifier,
            _number_key(portfolio_value),
            _number_key(proposed_weight),
            _number_key(alternative_return),
            _number_key(invalidation_clarity),
        )
        assessment = cache.get(key)
        if assessment is None:
            assessment = self.delegate.assess(
                candidate,
                portfolio_value=portfolio_value,
                proposed_weight=proposed_weight,
                alternative_return=alternative_return,
                invalidation_clarity=invalidation_clarity,
            )
            cache[key] = assessment
        return assessment


class MemoizedJointCandidateIntelligenceEngine:
    """Reuse the potentially O(N²) joint-candidate assessment inside one cycle."""

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self._active_cache: ContextVar[dict[tuple[object, ...], object] | None] = (
            ContextVar(
                f"global_rotation_joint_candidate_{id(self)}",
                default=None,
            )
        )

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def begin_cycle_cache(self) -> Token:
        return self._active_cache.set({})

    def end_cycle_cache(self, token: Token) -> None:
        self._active_cache.reset(token)

    @staticmethod
    def _profile_key(profile) -> tuple[object, ...]:
        return (
            getattr(profile, "candidate_identifier", None),
            tuple(getattr(profile, "factor_loadings", ()) or ()),
            getattr(profile, "correlation_bucket", None),
        )

    def assess(self, candidates, risk_assessments, exposure_profiles):
        cache = self._active_cache.get()
        profiles = tuple(exposure_profiles)
        if cache is None:
            return self.delegate.assess(
                candidates,
                risk_assessments,
                profiles,
            )
        key = (
            tuple(item.identifier for item in candidates),
            tuple(
                (
                    item.candidate_identifier,
                    item.proposed_weight,
                    item.probability_of_loss,
                    item.expected_shortfall,
                    item.stressed_execution_cost_return,
                    item.fragility_score,
                    item.hard_blocks,
                )
                for item in risk_assessments
            ),
            tuple(self._profile_key(item) for item in profiles),
        )
        result = cache.get(key)
        if result is None:
            result = self.delegate.assess(
                candidates,
                risk_assessments,
                profiles,
            )
            cache[key] = result
        return result


class PrecomputedSpecialistService:
    """Context-local packet reuse around an existing specialist service.

    The delegate remains the only packet producer. A bound packet may be reused only
    for the same candidate and the same historical-learning context. This keeps the
    preliminary and final CIO passes identical without mutating the canonical journal
    or creating a second specialist implementation.
    """

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self._active_packets: ContextVar[dict[str, object]] = ContextVar(
            f"global_rotation_specialist_packets_{id(self)}",
            default={},
        )

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    @contextmanager
    def bind_packets(self, packets: dict[str, object]) -> Iterator[None]:
        if not isinstance(packets, dict):
            raise TypeError("packets must be a dict")
        token = self._active_packets.set(dict(packets))
        try:
            yield
        finally:
            self._active_packets.reset(token)

    def analyze(self, candidate, context):
        packet = self._active_packets.get().get(candidate.identifier)
        if packet is None:
            return self.delegate.analyze(candidate, context)
        validate = getattr(packet, "validate_against", None)
        if callable(validate):
            validate(candidate)
        packet_learning = getattr(packet, "historical_learning", None)
        context_learning = getattr(context, "historical_learning", None)
        if packet_learning != context_learning:
            raise ValueError(
                "precomputed specialist packet historical-learning context changed "
                "between preliminary and final CIO passes"
            )
        return packet


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


__all__ = [
    "MemoizedCandidateRiskIntelligenceEngine",
    "MemoizedJointCandidateIntelligenceEngine",
    "PrecomputedSpecialistService",
    "assess_preliminary_global_conviction",
]
