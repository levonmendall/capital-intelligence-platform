"""Common economic yardstick for cross-asset marginal capital decisions.

Every candidate is converted to annualized expected log growth on its governed
scenario distribution, net of implementation cost and relative to the same annual
opportunity-cost return. Risk, evidence uncertainty, and liquidity are explicit
penalties.

Forward intelligence enters only when it already has economic units: the global
rotation layer's ``forward_impulse`` is the confidence-weighted expected-return impact
of governed forward signals. It shifts each point in the candidate return distribution
before log-growth is evaluated. Dimensionless labels such as asset class, momentum,
leadership score, causal score, or theme score do not receive arbitrary utility points.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import exp, isfinite, log1p
from typing import Sequence


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


def _annualized_return_metrics(
    candidate: object,
    *,
    adjustment: float,
    cost: float,
    annualizer: float,
) -> tuple[float, float]:
    """Return annualized expected-log growth and downside path damage.

    Canonical production candidates expose a governed scenario distribution and use
    that richer path. Older preview/rehearsal callers intentionally use the compact
    candidate summary contract instead. For those callers, ``net_expected_return`` is
    already after implementation cost, so it is not charged a second time; the
    explicit downside summary remains a separate path-damage input.
    """

    raw_distribution = getattr(candidate, "scenario_distribution", None)
    distribution = tuple(raw_distribution or ())
    if distribution:
        expected_log = 0.0
        downside_log = 0.0
        probability_total = 0.0
        for point in distribution:
            probability = float(getattr(point, "probability"))
            total_return = (
                float(getattr(point, "total_return"))
                + adjustment
                - cost
            )
            probability_total += probability
            log_return = _safe_log_return(total_return)
            expected_log += probability * log_return
            if log_return < 0.0:
                downside_log += probability * abs(log_return)
        if abs(probability_total - 1.0) > 1e-6:
            raise ValueError("candidate scenario probabilities must sum to one")
        return expected_log * annualizer, downside_log * annualizer

    net_expected_return = getattr(candidate, "net_expected_return", None)
    if isinstance(net_expected_return, bool) or not isinstance(
        net_expected_return,
        (int, float),
    ):
        raise ValueError(
            "candidate scenario distribution or net_expected_return is required"
        )
    net_expected = float(net_expected_return)
    if not isfinite(net_expected):
        raise ValueError("candidate net_expected_return must be finite")

    expected_downside = getattr(candidate, "expected_downside", 0.0)
    if isinstance(expected_downside, bool) or not isinstance(
        expected_downside,
        (int, float),
    ):
        raise ValueError("candidate expected_downside must be numeric")
    downside_return = float(expected_downside)
    if not isfinite(downside_return):
        raise ValueError("candidate expected_downside must be finite")

    expected_log = _safe_log_return(net_expected + adjustment)
    downside_after_cost = min(0.0, downside_return - cost)
    downside_log = (
        abs(_safe_log_return(downside_after_cost))
        if downside_after_cost < 0.0
        else 0.0
    )
    return expected_log * annualizer, downside_log * annualizer


@dataclass(frozen=True, slots=True)
class MarginalCompoundingValue:
    candidate_identifier: str
    forward_return_adjustment: float
    annualized_expected_log_growth: float
    annualized_alternative_log_growth: float
    downside_penalty: float
    uncertainty_penalty: float
    liquidity_penalty: float
    utility: float
    normalized_score: float
    policy_version: str = "marginal-compounding-value.v2"

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "forward_return_adjustment": self.forward_return_adjustment,
            "annualized_expected_log_growth": self.annualized_expected_log_growth,
            "annualized_alternative_log_growth": self.annualized_alternative_log_growth,
            "downside_penalty": self.downside_penalty,
            "uncertainty_penalty": self.uncertainty_penalty,
            "liquidity_penalty": self.liquidity_penalty,
            "utility": self.utility,
            "normalized_score": self.normalized_score,
            "policy_version": self.policy_version,
        }


def assess_marginal_compounding_value(
    candidate: object,
    *,
    forward_return_adjustment: float = 0.0,
) -> MarginalCompoundingValue:
    identifier = str(getattr(candidate, "identifier", "")).strip()
    if not identifier:
        raise ValueError("candidate identifier is required")
    horizon_days = int(getattr(candidate, "decision_horizon_days"))
    annualizer = _annual_factor(horizon_days)
    adjustment = _clip(float(forward_return_adjustment), -0.10, 0.10)
    cost = max(0.0, float(getattr(candidate, "implementation_cost_return", 0.0)))

    annualized_expected, annualized_downside = _annualized_return_metrics(
        candidate,
        adjustment=adjustment,
        cost=cost,
        annualizer=annualizer,
    )
    annual_alternative = float(getattr(candidate, "opportunity_cost_return", 0.0))
    alternative_log = _safe_log_return(annual_alternative)

    quality = getattr(candidate, "evidence_quality", None)
    evidence_score = _clip(float(getattr(quality, "score", 0.0)), 0.0, 1.0)
    evidence_ceiling = _clip(float(getattr(quality, "ceiling", 0.0)), 0.0, 1.0)
    reliability = min(evidence_score, evidence_ceiling)
    liquidity = _clip(float(getattr(candidate, "liquidity_score", 0.0)), 0.0, 1.0)

    # Expected log growth already embeds negative scenarios. This smaller additional
    # penalty represents path damage that can reduce future compounding capacity.
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
    # Stable monotonic normalization for rank/presentation compatibility. Utility is
    # the economic quantity; this score is only a bounded representation of it.
    normalized_score = 1.0 / (1.0 + exp(-4.0 * utility))
    return MarginalCompoundingValue(
        candidate_identifier=identifier,
        forward_return_adjustment=round(adjustment, 8),
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
    """Order cross-asset alternatives on comparable economic utility.

    Leadership, mispricing, causal, and theme diagnostics remain attached to every
    signal. Their economically expressed expected-return effect is already summarized
    in ``forward_impulse`` and therefore shifts the candidate's return distribution.
    Remaining dimensionless diagnostics are retained for specialist/CIO interpretation
    and deterministic tie-breaking, not converted into arbitrary utility points.
    """

    candidate_by_id = {
        str(getattr(item, "identifier")): item for item in candidates
    }
    values = []
    for signal in tuple(getattr(context, "signals", ()) or ()):
        candidate = candidate_by_id.get(str(getattr(signal, "candidate_identifier")))
        if candidate is None:
            continue
        assessment = assess_marginal_compounding_value(
            candidate,
            forward_return_adjustment=float(
                getattr(signal, "forward_impulse", 0.0)
            ),
        )
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
        policy_version=f"{policy_version}|marginal-compounding-value.v2",
    )


__all__ = [
    "MarginalCompoundingValue",
    "assess_marginal_compounding_value",
    "rerank_global_rotation_context",
]
