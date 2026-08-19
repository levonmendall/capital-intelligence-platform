"""Deterministic global marginal-capital optimizer for the non-authoritative preview.

The optimizer does not authorize a trade and cannot bypass final construction. It
chooses among already-reviewed, positive-conviction candidate caps using the same
annualized marginal-compounding-value yardstick used by global rotation, then applies
portfolio concentration and factor-overlap penalties. Its output is fed through the
canonical construction engine before the CIO sees any joint feasibility context.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Mapping, Sequence

from portfolio.marginal_compounding_value import assess_marginal_compounding_value


@dataclass(frozen=True, slots=True)
class OptimizedCandidateTarget:
    candidate_identifier: str
    target_weight: float
    marginal_utility: float
    opportunity_rank: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "target_weight": self.target_weight,
            "marginal_utility": self.marginal_utility,
            "opportunity_rank": self.opportunity_rank,
        }


@dataclass(frozen=True, slots=True)
class GlobalCompoundPortfolioProposal:
    targets: tuple[OptimizedCandidateTarget, ...]
    target_cash_weight: float
    expected_log_growth_score: float
    deployable_cash_used: float
    diagnostics: tuple[str, ...]
    policy_version: str = "global-compound-optimizer.v3-forward-adjusted-compounding"
    authorizes_capital: bool = False
    construction_authority: bool = False

    @property
    def target_by_candidate(self) -> dict[str, float]:
        return {item.candidate_identifier: item.target_weight for item in self.targets}

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "targets": [item.to_dict() for item in self.targets],
            "target_cash_weight": self.target_cash_weight,
            "expected_log_growth_score": self.expected_log_growth_score,
            "deployable_cash_used": self.deployable_cash_used,
            "diagnostics": list(self.diagnostics),
            "investment_authority": False,
            "construction_authority": False,
        }


def _finite(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    number = float(value)
    return number if isfinite(number) else float(default)


def _factor_similarity(first: object, second: object) -> float:
    left = dict(tuple(getattr(first, "factor_loadings", ()) or ()))
    right = dict(tuple(getattr(second, "factor_loadings", ()) or ()))
    names = set(left).union(right)
    if not names:
        return 0.0
    dot = sum(_finite(left.get(name)) * _finite(right.get(name)) for name in names)
    nl = sqrt(sum(_finite(left.get(name)) ** 2 for name in names))
    nr = sqrt(sum(_finite(right.get(name)) ** 2 for name in names))
    if nl <= 0.0 or nr <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (nl * nr)))


def _profile(portfolio: object, candidate_identifier: str) -> object | None:
    getter = getattr(portfolio, "profile", None)
    if not callable(getter):
        return None
    try:
        return getter(candidate_identifier)
    except (KeyError, ValueError):
        return None


def _current_weight(portfolio: object, candidate: object) -> float:
    getter = getattr(portfolio, "current_weight", None)
    symbol = str(getattr(getattr(candidate, "instrument", None), "symbol", ""))
    if callable(getter) and symbol:
        return max(0.0, _finite(getter(symbol)))
    return max(0.0, _finite(getattr(candidate, "current_portfolio_weight", 0.0)))


def _base_utility(candidate: object, signal: object) -> float:
    """Return one comparable, forward-adjusted economic quantity."""

    assessment = assess_marginal_compounding_value(
        candidate,
        forward_return_adjustment=_finite(
            getattr(signal, "forward_impulse", 0.0),
        ),
    )
    signal_candidate_identifier = str(
        getattr(signal, "candidate_identifier", "")
    ).strip()
    if (
        signal_candidate_identifier
        and signal_candidate_identifier != assessment.candidate_identifier
    ):
        raise ValueError("global rotation signal does not match candidate utility")
    return assessment.utility


def optimize_global_compound_targets(
    *,
    candidates: Sequence[object],
    rotation_context: object,
    conviction_targets: Mapping[str, float | None],
    portfolio: object,
    minimum_cash_weight: float,
    increment: float = 0.0025,
) -> GlobalCompoundPortfolioProposal:
    """Allocate deployable cash among positive candidate caps by marginal utility."""

    if increment <= 0.0 or increment > 0.01:
        raise ValueError("increment must be in (0, 1%]")
    by_signal = dict(getattr(rotation_context, "by_candidate", {}) or {})
    current_cash = max(0.0, min(1.0, _finite(getattr(portfolio, "cash_weight", 0.0))))
    reserve = max(0.0, min(1.0, float(minimum_cash_weight)))
    available = max(0.0, current_cash - reserve)

    candidate_by_id = {str(getattr(item, "identifier")): item for item in candidates}
    current = {
        identifier: _current_weight(portfolio, candidate)
        for identifier, candidate in candidate_by_id.items()
    }
    caps: dict[str, float] = {}
    for identifier, candidate in candidate_by_id.items():
        proposed = conviction_targets.get(identifier)
        if proposed is None:
            caps[identifier] = current[identifier]
            continue
        cap = max(0.0, min(float(proposed), _finite(getattr(candidate, "maximum_position_weight", 1.0), 1.0)))
        caps[identifier] = cap

    # Honor preliminary reductions immediately in the preview target set; increases
    # compete for the same marginal cash pool.
    targets = {identifier: min(current[identifier], caps[identifier]) for identifier in candidate_by_id}
    released = sum(max(0.0, current[item] - targets[item]) for item in targets)
    deployable = min(1.0 - reserve, available + released)
    used = 0.0
    last_utility: dict[str, float] = {identifier: 0.0 for identifier in candidate_by_id}

    while used + 1e-12 < deployable:
        best_identifier: str | None = None
        best_utility = 0.0
        for identifier, candidate in candidate_by_id.items():
            signal = by_signal.get(identifier)
            if signal is None or targets[identifier] + 1e-12 >= caps[identifier]:
                continue
            utility = _base_utility(candidate, signal)
            if utility <= 0.0:
                continue
            profile = _profile(portfolio, identifier)
            concentration_penalty = 0.0
            for other_identifier, other_weight in targets.items():
                if other_identifier == identifier or other_weight <= 0.0:
                    continue
                other_profile = _profile(portfolio, other_identifier)
                if profile is None or other_profile is None:
                    continue
                same_sector = (
                    str(getattr(profile, "sector", ""))
                    and str(getattr(profile, "sector", ""))
                    == str(getattr(other_profile, "sector", ""))
                )
                same_bucket = (
                    str(getattr(profile, "correlation_bucket", ""))
                    and str(getattr(profile, "correlation_bucket", ""))
                    == str(getattr(other_profile, "correlation_bucket", ""))
                )
                similarity = max(0.0, _factor_similarity(profile, other_profile))
                concentration_penalty += other_weight * (
                    0.16 * float(bool(same_sector))
                    + 0.18 * float(bool(same_bucket))
                    + 0.20 * similarity
                )
            utility -= concentration_penalty
            # Diminishing marginal utility prevents a single leader from absorbing all
            # available cash before the constructor applies concentration constraints.
            utility -= 0.35 * targets[identifier]
            if utility > best_utility + 1e-12 or (
                abs(utility - best_utility) <= 1e-12
                and best_identifier is not None
                and int(getattr(signal, "rank", 10**9))
                < int(getattr(by_signal[best_identifier], "rank", 10**9))
            ):
                best_identifier = identifier
                best_utility = utility
        if best_identifier is None or best_utility <= 0.0:
            break
        room = max(0.0, caps[best_identifier] - targets[best_identifier])
        step = min(increment, room, deployable - used)
        if step <= 1e-12:
            break
        targets[best_identifier] += step
        used += step
        last_utility[best_identifier] = best_utility

    target_cash = max(reserve, min(1.0, current_cash + released - used))
    ordered = sorted(
        candidate_by_id,
        key=lambda identifier: (
            int(getattr(by_signal.get(identifier), "rank", 10**9)),
            identifier,
        ),
    )
    proposal_targets = tuple(
        OptimizedCandidateTarget(
            candidate_identifier=identifier,
            target_weight=round(targets[identifier], 8),
            marginal_utility=round(last_utility[identifier], 8),
            opportunity_rank=int(getattr(by_signal.get(identifier), "rank", len(ordered) + 1)),
        )
        for identifier in ordered
    )
    growth_score = sum(
        max(0.0, targets[identifier] - current[identifier])
        * max(0.0, last_utility[identifier])
        for identifier in ordered
    )
    diagnostics = (
        f"Deployable cash={deployable:.2%}; optimizer used={used:.2%}; target cash={target_cash:.2%}.",
        "Every candidate competes on annualized expected log growth after costs, downside, evidence uncertainty, liquidity, the same opportunity-cost hurdle, and economically expressed confidence-weighted forward return impacts.",
        "Candidate caps come from the preliminary six-specialist conviction pass; the optimizer cannot raise them.",
        "Final canonical construction remains authoritative for correlation, downside, liquidity, turnover, cost and implementation constraints.",
    )
    return GlobalCompoundPortfolioProposal(
        targets=proposal_targets,
        target_cash_weight=round(target_cash, 8),
        expected_log_growth_score=round(growth_score, 8),
        deployable_cash_used=round(used, 8),
        diagnostics=diagnostics,
    )


__all__ = [
    "GlobalCompoundPortfolioProposal",
    "OptimizedCandidateTarget",
    "optimize_global_compound_targets",
]
