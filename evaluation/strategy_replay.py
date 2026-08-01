"""Research-only evaluation of persistent-cash historical replay evidence.

This module reads an already-produced canonical historical replay report. It cannot
change qualification, specialist analysis, CIO authority, construction, portfolio
state, paper execution, or real-money authority.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence


CAPABILITY_AUTHORITY_REASON = (
    "instrument is intelligence-only because its market or economic exposure "
    "lacks a configured capability authority"
)

_REASON_CATEGORY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("capability_authority", ("capability authority", "intelligence-only")),
    ("evidence_quality", ("evidence-quality", "evidence quality")),
    ("liquidity", ("liquidity",)),
    ("expected_return", ("expected return", "return hurdle")),
    ("cash_hurdle", ("cash hurdle", "opportunity edge", "best alternative")),
    ("success_probability", ("probability of success", "disclosed scenarios")),
    ("downside", ("expected downside", "downside")),
    ("worst_case_portfolio_loss", ("worst-case portfolio loss", "worst case portfolio loss")),
)


class StrategyReplayEvaluationError(ValueError):
    """Raised when a replay report is unsafe, malformed, or not evaluable."""


@dataclass(frozen=True, slots=True)
class ReplayObservation:
    cutoff: str
    identifier: str
    symbol: str
    asset_class: str
    decision_stage: str
    canonical_cio_decision: bool
    universe_disposition: str
    qualification_outcome: str
    qualification_reasons: tuple[str, ...]
    opportunity_edge: float | None
    final_confidence: float | None
    underlying_return_at_horizon: float | None
    effective_opportunity_cost: float | None
    realized_outcome: str | None

    @property
    def reason_categories(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(categorize_reason(item) for item in self.qualification_reasons))

    @property
    def excess_return_at_horizon(self) -> float | None:
        if self.underlying_return_at_horizon is None:
            return None
        return self.underlying_return_at_horizon - float(
            self.effective_opportunity_cost or 0.0
        )


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    return None


def categorize_reason(reason: str) -> str:
    value = reason.strip().lower()
    for category, markers in _REASON_CATEGORY_MARKERS:
        if any(marker in value for marker in markers):
            return category
    return "other"


def validate_replay_report(report: Mapping[str, Any]) -> None:
    required_true = ("research_only",)
    required_false = (
        "execution_authorized",
        "paper_execution_authorized",
        "real_money_authorized",
        "policy_promotion_authorized",
        "performance_claims_authorized",
    )
    for key in required_true:
        if report.get(key) is not True:
            raise StrategyReplayEvaluationError(f"{key} must be true")
    for key in required_false:
        if report.get(key) is not False:
            raise StrategyReplayEvaluationError(f"{key} must be false")
    if not isinstance(report.get("decisions"), list):
        raise StrategyReplayEvaluationError("decisions must be a list")
    if not str(report.get("schema_version", "")).startswith(
        "canonical-historical-replay."
    ):
        raise StrategyReplayEvaluationError(
            "unsupported canonical historical replay schema"
        )


def replay_observations(report: Mapping[str, Any]) -> tuple[ReplayObservation, ...]:
    validate_replay_report(report)
    values: list[ReplayObservation] = []
    seen: set[str] = set()
    for cutoff in report.get("decisions", ()):
        if not isinstance(cutoff, Mapping):
            continue
        cutoff_value = str(cutoff.get("cutoff") or "")
        for payload in cutoff.get("decisions", ()):
            if not isinstance(payload, Mapping):
                continue
            identifier = str(payload.get("identifier") or "")
            if not identifier:
                raise StrategyReplayEvaluationError(
                    "every replay observation requires an identifier"
                )
            if identifier in seen:
                raise StrategyReplayEvaluationError(
                    f"duplicate replay observation: {identifier}"
                )
            seen.add(identifier)
            reasons = tuple(
                str(item).strip()
                for item in payload.get("qualification_reasons", ())
                if str(item).strip()
            )
            values.append(
                ReplayObservation(
                    cutoff=cutoff_value,
                    identifier=identifier,
                    symbol=str(payload.get("symbol") or "UNKNOWN").upper(),
                    asset_class=str(payload.get("asset_class") or "unknown"),
                    decision_stage=str(payload.get("decision_stage") or "unknown"),
                    canonical_cio_decision=bool(
                        payload.get("canonical_cio_decision", False)
                    ),
                    universe_disposition=str(
                        payload.get("universe_disposition") or "unknown"
                    ),
                    qualification_outcome=str(
                        payload.get("qualification_outcome") or "unknown"
                    ),
                    qualification_reasons=reasons,
                    opportunity_edge=_optional_float(payload.get("opportunity_edge")),
                    final_confidence=_optional_float(payload.get("final_confidence")),
                    underlying_return_at_horizon=_optional_float(
                        payload.get("underlying_return_at_decision_horizon")
                    ),
                    effective_opportunity_cost=_optional_float(
                        payload.get("effective_opportunity_cost")
                    ),
                    realized_outcome=(
                        None
                        if payload.get("realized_outcome") is None
                        else str(payload.get("realized_outcome"))
                    ),
                )
            )
    return tuple(values)


def _percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rounded(value: float | None, digits: int = 8) -> float | None:
    return None if value is None else round(float(value), digits)


def _outcome_summary(observations: Iterable[ReplayObservation]) -> dict[str, Any]:
    values = tuple(observations)
    outcomes = Counter(
        item.realized_outcome or "unresolved"
        for item in values
    )
    excess = tuple(
        item.excess_return_at_horizon
        for item in values
        if item.excess_return_at_horizon is not None
    )
    return {
        "observation_count": len(values),
        "resolved_outcome_count": len(excess),
        "outcome_counts": dict(sorted(outcomes.items())),
        "mean_excess_return": _rounded(mean(excess) if excess else None),
        "median_excess_return": _rounded(median(excess) if excess else None),
        "p10_excess_return": _rounded(_percentile(excess, 0.10)),
        "p90_excess_return": _rounded(_percentile(excess, 0.90)),
        "minimum_excess_return": _rounded(min(excess) if excess else None),
        "maximum_excess_return": _rounded(max(excess) if excess else None),
    }


def _ablation_summary(observations: Sequence[ReplayObservation]) -> dict[str, Any]:
    categories = sorted(
        {category for item in observations for category in item.reason_categories}
    )
    one_at_a_time: dict[str, int] = {}
    for category in categories:
        one_at_a_time[category] = sum(
            not set(item.reason_categories).difference({category})
            for item in observations
        )

    after_capability = [
        item for item in observations
        if "capability_authority" in item.reason_categories
    ]
    secondary_counts = Counter(
        category
        for item in after_capability
        for category in item.reason_categories
        if category != "capability_authority"
    )
    conditional_pass_count = sum(
        set(item.reason_categories) == {"capability_authority"}
        for item in after_capability
    )
    paired: dict[str, int] = {}
    for category in sorted(secondary_counts):
        paired[category] = sum(
            not set(item.reason_categories).difference(
                {"capability_authority", category}
            )
            for item in after_capability
        )

    return {
        "one_reason_removed_pass_counts": one_at_a_time,
        "capability_authority_observation_count": len(after_capability),
        "capability_only_pass_count": conditional_pass_count,
        "secondary_reason_counts": dict(sorted(secondary_counts.items())),
        "capability_plus_one_secondary_removed_pass_counts": paired,
        "committee_ablation_evaluable": any(
            item.canonical_cio_decision for item in observations
        ),
        "construction_ablation_evaluable": any(
            item.canonical_cio_decision for item in observations
        ),
    }


def _chronological_split(
    observations: Sequence[ReplayObservation],
    *,
    development_fraction: float,
) -> tuple[set[str], set[str]]:
    if not 0.5 <= development_fraction < 1.0:
        raise ValueError("development_fraction must be in [0.5, 1.0)")
    cutoffs = sorted({item.cutoff for item in observations if item.cutoff})
    if len(cutoffs) < 2:
        return set(cutoffs), set()
    split = max(1, min(len(cutoffs) - 1, int(len(cutoffs) * development_fraction)))
    return set(cutoffs[:split]), set(cutoffs[split:])


def _eligible_for_variant(
    observation: ReplayObservation,
    *,
    variant: str,
) -> bool:
    reasons = set(observation.reason_categories)
    edge = observation.opportunity_edge
    if variant == "alternative_cash_hurdle_minus_50bp":
        return (
            reasons == {"capability_authority"}
            and edge is not None
            and edge > -0.005
        )
    if edge is None or edge <= 0.0:
        return False
    if variant in {
        "capability_certified_continuous_ranking",
        "capability_certified_starter_position",
        "capability_certified_graduated_sizing",
    }:
        return reasons == {"capability_authority"}
    if variant == "capability_plus_downside_pair_relaxation":
        return (
            "capability_authority" in reasons
            and reasons.difference(
                {
                    "capability_authority",
                    "downside",
                    "worst_case_portfolio_loss",
                }
            )
            == set()
        )
    return False


def _variant_weight(observation: ReplayObservation, *, variant: str) -> float:
    if variant in {
        "capability_certified_continuous_ranking",
        "capability_certified_starter_position",
        "capability_plus_downside_pair_relaxation",
        "alternative_cash_hurdle_minus_50bp",
    }:
        return 0.01
    if variant == "capability_certified_graduated_sizing":
        confidence = max(0.0, min(1.0, observation.final_confidence or 0.0))
        edge = max(0.0, min(0.10, observation.opportunity_edge or 0.0))
        return round(0.01 + 0.04 * confidence * (edge / 0.10), 8)
    return 0.0


def _evaluate_variant(
    observations: Sequence[ReplayObservation],
    *,
    variant: str,
    cutoff_scope: set[str],
) -> dict[str, Any]:
    by_cutoff: dict[str, list[ReplayObservation]] = defaultdict(list)
    for item in observations:
        if item.cutoff in cutoff_scope and _eligible_for_variant(item, variant=variant):
            by_cutoff[item.cutoff].append(item)
    selected: list[ReplayObservation] = []
    for cutoff in sorted(by_cutoff):
        candidates = sorted(
            by_cutoff[cutoff],
            key=lambda item: (
                item.opportunity_edge if item.opportunity_edge is not None else -math.inf,
                item.final_confidence if item.final_confidence is not None else -math.inf,
                item.symbol,
            ),
            reverse=True,
        )
        selected.append(candidates[0])
    resolved = [
        item for item in selected if item.excess_return_at_horizon is not None
    ]
    weighted = [
        float(item.excess_return_at_horizon) * _variant_weight(item, variant=variant)
        for item in resolved
        if item.excess_return_at_horizon is not None
    ]
    return {
        "status": "evaluable_research_only",
        "selected_cutoff_count": len(selected),
        "resolved_selection_count": len(resolved),
        "selection_symbols": dict(
            sorted(Counter(item.symbol for item in selected).items())
        ),
        "positive_excess_selection_count": sum(
            float(item.excess_return_at_horizon) > 0.0
            for item in resolved
            if item.excess_return_at_horizon is not None
        ),
        "negative_excess_selection_count": sum(
            float(item.excess_return_at_horizon) < 0.0
            for item in resolved
            if item.excess_return_at_horizon is not None
        ),
        "median_excess_return": _rounded(
            median(
                float(item.excess_return_at_horizon)
                for item in resolved
                if item.excess_return_at_horizon is not None
            )
            if resolved
            else None
        ),
        "p10_excess_return": _rounded(
            _percentile(
                [
                    float(item.excess_return_at_horizon)
                    for item in resolved
                    if item.excess_return_at_horizon is not None
                ],
                0.10,
            )
        ),
        "mean_weighted_excess_contribution": _rounded(
            mean(weighted) if weighted else None
        ),
        "minimum_weighted_excess_contribution": _rounded(
            min(weighted) if weighted else None
        ),
        "maximum_weighted_excess_contribution": _rounded(
            max(weighted) if weighted else None
        ),
        "maximum_position_weight": _rounded(
            max(
                (_variant_weight(item, variant=variant) for item in selected),
                default=0.0,
            )
        ),
        "portfolio_compounding_simulated": False,
        "performance_claims_authorized": False,
    }


def _shadow_variant_summary(
    observations: Sequence[ReplayObservation],
    *,
    development_fraction: float,
) -> dict[str, Any]:
    development, evaluation = _chronological_split(
        observations,
        development_fraction=development_fraction,
    )
    variants = (
        "capability_certified_continuous_ranking",
        "capability_certified_starter_position",
        "capability_certified_graduated_sizing",
        "capability_plus_downside_pair_relaxation",
        "alternative_cash_hurdle_minus_50bp",
    )
    evaluated: dict[str, Any] = {}
    for variant in variants:
        evaluated[variant] = {
            "development": _evaluate_variant(
                observations, variant=variant, cutoff_scope=development
            ),
            "evaluation": _evaluate_variant(
                observations, variant=variant, cutoff_scope=evaluation
            ),
        }
    not_evaluable_reason = (
        "The certified replay contains no canonical CIO decision observations; "
        "specialist, disagreement, CIO synthesis, sizing, and construction variants "
        "cannot be identified from pre-CIO qualification records."
    )
    for variant in (
        "reliability_weighted_specialist_evidence",
        "explicit_specialist_disagreement",
        "portfolio_marginal_contribution",
        "alternative_cio_synthesis",
    ):
        evaluated[variant] = {
            "status": "not_evaluable",
            "reason": not_evaluable_reason,
        }
    return {
        "development_fraction": development_fraction,
        "development_cutoff_count": len(development),
        "evaluation_cutoff_count": len(evaluation),
        "variants": evaluated,
        "shadow_only": True,
        "construction_authority": False,
        "execution_authority": False,
        "policy_promotion_authority": False,
        "performance_claims_authorized": False,
    }


def evaluate_strategy_replay(
    report: Mapping[str, Any],
    *,
    source_artifact: Mapping[str, Any] | None = None,
    development_fraction: float = 0.70,
) -> dict[str, Any]:
    observations = replay_observations(report)
    reason_counts = Counter(
        reason for item in observations for reason in item.qualification_reasons
    )
    reason_category_counts = Counter(
        category for item in observations for category in item.reason_categories
    )
    stage_counts = Counter(item.decision_stage for item in observations)
    symbol_counts = Counter(item.symbol for item in observations)
    asset_class_counts = Counter(item.asset_class for item in observations)
    disposition_counts = Counter(item.universe_disposition for item in observations)
    canonical_count = sum(item.canonical_cio_decision for item in observations)
    universal_capability_block = bool(observations) and all(
        CAPABILITY_AUTHORITY_REASON in item.qualification_reasons
        for item in observations
    )
    pilot_scope_represented = any(
        item.asset_class in {"us_etf", "us_equity", "fixed_income", "commodity", "real_estate"}
        for item in observations
    )

    verdict = (
        "NO_GO_FOR_STRATEGY_CHANGE_RESET_OR_FORMAL_EXPERIMENT"
        if (
            canonical_count == 0
            or universal_capability_block
            or not pilot_scope_represented
        )
        else "REQUIRES_HUMAN_GOVERNANCE_REVIEW"
    )
    result = {
        "schema_version": "push2-strategy-replay-evaluation.v1",
        "generated_at": str(report.get("generated_at") or ""),
        "source": {
            "replay_schema_version": report.get("schema_version"),
            "replay_generated_at": report.get("generated_at"),
            "start_date": report.get("start_date"),
            "end_date": report.get("end_date"),
            "runtime_version": report.get("runtime_version"),
            **dict(source_artifact or {}),
        },
        "replay": {
            "decision_cutoff_count": report.get("decision_cutoff_count"),
            "canonical_cio_invoked_count": report.get("canonical_cio_invoked_count"),
            "blocked_cutoff_count": report.get("blocked_cutoff_count"),
            "certification_ready": report.get("certification_ready"),
            "initial_portfolio_value": report.get("initial_portfolio_value"),
            "ending_portfolio_value": report.get("ending_portfolio_value"),
            "ending_cash_weight": report.get("ending_cash_weight"),
            "observation_count": len(observations),
            "canonical_cio_decision_observation_count": canonical_count,
            "stage_counts": dict(sorted(stage_counts.items())),
            "symbol_counts": dict(sorted(symbol_counts.items())),
            "asset_class_counts": dict(sorted(asset_class_counts.items())),
            "universe_disposition_counts": dict(sorted(disposition_counts.items())),
            "qualification_reason_counts": dict(sorted(reason_counts.items())),
            "qualification_reason_category_counts": dict(
                sorted(reason_category_counts.items())
            ),
            "universal_capability_authority_block": universal_capability_block,
            "current_allocatable_pilot_scope_represented": pilot_scope_represented,
            "outcomes": _outcome_summary(observations),
        },
        "ablation": _ablation_summary(observations),
        "shadow_variants": _shadow_variant_summary(
            observations,
            development_fraction=development_fraction,
        ),
        "strategy_go_no_go": {
            "verdict": verdict,
            "canonical_strategy_changed": False,
            "thresholds_changed": False,
            "portfolio_reset_authorized": False,
            "formal_experiment_launch_authorized": False,
            "primary_findings": [
                (
                    "Every historical observation was blocked before specialist/CIO "
                    "synthesis by missing capability authority."
                    if universal_capability_block
                    else "No universal capability-authority block was established."
                ),
                (
                    f"The replay contains {canonical_count} canonical CIO decision "
                    "observations."
                ),
                (
                    "The current allocatable pilot scope is represented."
                    if pilot_scope_represented
                    else (
                        "The replay does not represent the current allocatable pilot "
                        "scope; it cannot validate broad portfolio strategy."
                    )
                ),
                (
                    "Committee/CIO variants are not identifiable until observations "
                    "reach those stages."
                    if canonical_count == 0
                    else "Committee/CIO variants may be evaluated."
                ),
            ],
            "required_go_conditions": [
                "Deploy the diagnostic release and collect production persistent-cash and committee/CIO traces.",
                "Replay the actual decision-eligible pilot instruments with certified point-in-time evidence across multiple regimes.",
                "Include observations that reach six-specialist analysis, CIO decisions, initial targets, construction, and implementation.",
                "Run chronological development/evaluation shadow comparisons without granting authority.",
                "Obtain explicit human governance approval before any strategy change, portfolio reset, or formal experiment launch.",
            ],
        },
        "authority": {
            "research_only": True,
            "cio_authority_changed": False,
            "specialist_authority_changed": False,
            "construction_authority_changed": False,
            "execution_authority_changed": False,
            "real_money_authorized": False,
            "policy_promotion_authorized": False,
            "performance_claims_authorized": False,
        },
    }
    return result


def evaluate_strategy_replay_file(
    path: str | Path,
    *,
    source_artifact: Mapping[str, Any] | None = None,
    development_fraction: float = 0.70,
) -> dict[str, Any]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(report, Mapping):
        raise StrategyReplayEvaluationError("replay report must be a JSON object")
    return evaluate_strategy_replay(
        report,
        source_artifact=source_artifact,
        development_fraction=development_fraction,
    )


__all__ = [
    "CAPABILITY_AUTHORITY_REASON",
    "ReplayObservation",
    "StrategyReplayEvaluationError",
    "categorize_reason",
    "evaluate_strategy_replay",
    "evaluate_strategy_replay_file",
    "replay_observations",
    "validate_replay_report",
]
