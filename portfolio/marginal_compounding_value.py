"""Common economic yardstick for cross-asset marginal capital decisions.

Every candidate is converted to annualized expected log growth on its own governed
scenario distribution, net of implementation cost and relative to the same annual
opportunity-cost return.  Risk, evidence uncertainty, and liquidity are explicit
penalties.  Asset-class labels, momentum labels, or leadership scores do not receive
independent utility points here; they are expected to influence the candidate's
point-in-time return distribution upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import exp, isfinite, log1p
from typing import Mapping, Sequence


_EPSILON = 1e-9


def _clip(value: float, low: float, high: float) -> float:
    if not isfinite(float(value)):
        raise ValueError("marginal compounding values must be finite")
    return max(low, min(high, float(value)))


def _annual_factor(days: int) -> float:
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("decision horizon must be a positive integer")
    return 365.25 / float(days)


def _safe_log_return(total_return: float) -> float:
    return log1p(max(-0.999999, float(total_return)))


@dataclass(frozen=True, slots=True)
class MarginalCompoundingValue:
    candidate_identifier: str
    annualized_expected_log_growth: float
    annualized_alternative_log_growth: float
    downside_penalty: float
    uncertainty_penalty: float
    liquidity_penalty: float
    utility: float
    normalized_score: float
    policy_version: str = "marginal-compounding-value.v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "annualized_expected_log_growth": self.annualized_expected_log_growth,
            "annualized_alternative_log_growth": self.annualized_alternative_log_growth,
            "downside_penalty": self.downside_penalty,
            "uncertainty_penalty": self.uncertainty_penalty,
            "liquidity_penalty": self.liquidity_penalty,
            "utility": self.utility,
            "normalized_score": self.normalized_score,
            "policy_version": self.policy_version,
        }


def assess_marginal_compounding_value(candidate: object) -> MarginalCompoundingValue:
    identifier = str(getattr(candidate, "identifier", "")).strip()
    if not identifier:
        raise ValueError("candidate identifier is required")
    horizon_days = int(getattr(candidate, "decision_horizon_days"))
    annualizer = _annual_factor(horizon_days)
    distribution = tuple(getattr(candidate, "scenario_distribution"))
    if not distribution:
        raise ValueError("candidate scenario distribution is required")
    cost = max(0.0, float(getattr(candidate, "implementation_cost_return", 0.0)))

    expected_log = 0.0
    downside_log = 0.0
    probability_total = 0.0
    for point in distribution:
        probability = float(getattr(point, "probability"))
        total_return = float(getattr(point, "total_return")) - cost
        probability_total += probability
        log_return = _safe_log_return(total_return)
        expected_log += probability * log_return
        if log_return < 0.0:
            downside_log += probability * abs(log_return)
    if abs(probability_total - 1.0) > 1e-6:
        raise ValueError("candidate scenario probabilities must sum to one")

    annualized_expected = expected_log * annualizer
    annualized_downside = downside_log * annualizer
    annual_alternative = float(getattr(candidate, "opportunity_cost_return", 0.0))
    alternative_log = _safe_log_return(annual_alternative)

    quality = getattr(candidate, "evidence_quality", None)
    evidence_score = _clip(float(getattr(quality, "score", 0.0)), 0.0, 1.0)
    evidence_ceiling = _clip(float(getattr(quality, "ceiling", 0.0)), 0.0, 1.0)
    reliability = min(evidence_score, evidence_ceiling)
    liquidity = _clip(float(getattr(candidate, "liquidity_score", 0.0)), 0.0, 1.0)

    # Downside is deliberately penalized less than one-for-one because expected log
    # growth already captures negative scenarios.  This extra term represents the
    # portfolio's aversion to paths that can impair future compounding capacity.
    downside_penalty = 0.20 * annualized_downside
    uncertainty_penalty = (1.0 - reliability) * (
        0.08 + 0.25 * abs(annualized_expected)
    )
    liquidity_penalty = (1.0 - liquidity) * 0.05
    utility = (
        annualized_expected
        - alternative_log
        - downside_penalty
        - uncertainty_penalty
        - liquidity_penalty
    )
    # A stable monotonic normalization for UI/ranking compatibility.  The utility is
    # the economic quantity; the score is only a bounded representation of it.
    normalized_score = 1.0 / (1.0 + exp(-4.0 * utility))
    return MarginalCompoundingValue(
        candidate_identifier=identifier,
        annualized_expected_log_growth=round(annualized_expected, 8),
        annualized_alternative_log_growth=round(alternative_log, 8),
        downside_penalty=round(downside_penalty, 8),
        uncertainty_penalty=round(uncertainty_penalty, 8),
        liquidity_penalty=round(liquidity_penalty, 8),
        utility=round(utility, 8),
        normalized_score=round(normalized_score, 8),
    )


def rerank_global_rotation_context(
    context: object,
    *,
    candidates: Sequence[object],
):
    """Replace heuristic cross-asset ordering with comparable economic utility.

    Leadership, mispricing, causal, and theme fields remain attached to each signal as
    diagnostics and upstream evidence.  The final cross-asset rank and bounded score
    are determined by marginal compounding value, with the prior signal score used
    only as a deterministic tie-breaker.
    """

    candidate_by_id = {
        str(getattr(item, "identifier")): item for item in candidates
    }
    values = []
    for signal in tuple(getattr(context, "signals", ()) or ()):
        candidate = candidate_by_id.get(str(getattr(signal, "candidate_identifier")))
        if candidate is None:
            continue
        assessment = assess_marginal_compounding_value(candidate)
        values.append((assessment, signal))
    if len(values) != len(tuple(getattr(context, "signals", ()) or ())):
        raise ValueError("global rotation context and candidate set do not reconcile")
    values.sort(
        key=lambda item: (
            item[0].utility,
            float(getattr(item[1], "score", 0.0)),
            str(getattr(item[1], "candidate_identifier", "")),
        ),
        reverse=True,
    )
    reranked = tuple(
        replace(
            signal,
            rank=index,
            score=assessment.normalized_score,
            longitudinal_state=(
                str(getattr(signal, "longitudinal_state", "new"))
                + f"|mcv={assessment.utility:+.6f}"
            ),
        )
        for index, (assessment, signal) in enumerate(values, start=1)
    )
    policy_version = str(getattr(context, "policy_version", "global-opportunity-rotation"))
    return replace(
        context,
        signals=reranked,
        policy_version=f"{policy_version}|marginal-compounding-value.v1",
    )


__all__ = [
    "MarginalCompoundingValue",
    "assess_marginal_compounding_value",
    "rerank_global_rotation_context",
]
