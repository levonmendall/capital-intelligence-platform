"""Point-in-time statistical certification for the governed CIO process.

Measurement is separate from authority. This module asks whether resolved CIO
decisions actually increased portfolio wealth versus cash and the best governed
alternative. No result here changes thresholds, specialist weights, construction
policy, or capital authority automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import sqrt
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


class DecisionProcessOutcomeClass(str, Enum):
    GOOD_PROCESS_GOOD_OUTCOME = "good_process_good_outcome"
    GOOD_PROCESS_BAD_OUTCOME = "good_process_bad_outcome"
    WEAK_PROCESS_LUCKY_OUTCOME = "weak_process_lucky_outcome"
    WEAK_PROCESS_BAD_OUTCOME = "weak_process_bad_outcome"


@dataclass(frozen=True, slots=True)
class WalkForwardObservation:
    identifier: str
    decision_as_of: datetime
    knowledge_cutoff: datetime
    training_window_end: datetime
    provider_available_from: datetime
    outcome_observed_at: datetime
    asset_class: str
    regime: str
    confidence_bucket: str
    horizon_days: int
    information_completeness: float
    schema_version: str = "walk-forward-observation.v1"

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("walk-forward observation identifier cannot be empty")
        for name in (
            "decision_as_of",
            "knowledge_cutoff",
            "training_window_end",
            "provider_available_from",
            "outcome_observed_at",
        ):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        if not 0.0 <= float(self.information_completeness) <= 1.0:
            raise ValueError("information_completeness must be between zero and one")


@dataclass(frozen=True, slots=True)
class WalkForwardIntegrityReport:
    observation_count: int
    distinct_decision_dates: int
    asset_classes: tuple[str, ...]
    regimes: tuple[str, ...]
    future_knowledge_violations: tuple[str, ...]
    training_leakage_violations: tuple[str, ...]
    provider_availability_violations: tuple[str, ...]
    outcome_timing_violations: tuple[str, ...]
    point_in_time_passed: bool
    survivorship_claim_authorized: bool = False
    schema_version: str = "walk-forward-integrity-report.v1"

    def __post_init__(self) -> None:
        if self.survivorship_claim_authorized:
            raise ValueError("walk-forward report cannot authorize survivorship claims")


@dataclass(frozen=True, slots=True)
class CIOStatisticalCertificationPolicy:
    minimum_resolved_decisions: int = 200
    minimum_distinct_decision_dates: int = 60
    minimum_asset_classes: int = 3
    minimum_regimes: int = 2
    maximum_missing_outcome_fraction: float = 0.05
    minimum_positive_dollar_value_rate: float = 0.50
    minimum_mean_excess_return_vs_cash: float = 0.0
    minimum_mean_excess_return_vs_best_alternative: float = 0.0
    maximum_candidate_expected_return_mae: float = 0.15
    maximum_portfolio_improvement_mae: float = 0.10
    schema_version: str = "cio-statistical-certification-policy.v1"

    def __post_init__(self) -> None:
        for name in (
            "minimum_resolved_decisions",
            "minimum_distinct_decision_dates",
            "minimum_asset_classes",
            "minimum_regimes",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.maximum_missing_outcome_fraction <= 1.0:
            raise ValueError("maximum_missing_outcome_fraction must be between zero and one")
        if not 0.0 <= self.minimum_positive_dollar_value_rate <= 1.0:
            raise ValueError("minimum_positive_dollar_value_rate must be between zero and one")


@dataclass(frozen=True, slots=True)
class DecisionValidationRow:
    packet_identifier: str
    decision_as_of: datetime
    outcome_observed_at: datetime
    asset_class: str
    economic_exposure_class: str
    cio_confidence: float
    process_quality_score: float
    expected_candidate_return: float
    realized_candidate_return: float
    expected_portfolio_improvement: float
    realized_portfolio_excess_vs_cash: float
    realized_portfolio_excess_vs_best_alternative: float
    expected_dollar_value_added: float
    realized_dollar_value_added_vs_cash: float
    realized_dollar_value_added_vs_best_alternative: float
    outcome_class: DecisionProcessOutcomeClass
    evidence_identifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SegmentValidation:
    dimension: str
    value: str
    observation_count: int
    mean_excess_return_vs_cash: float
    mean_excess_return_vs_best_alternative: float
    positive_dollar_value_rate: float
    expected_return_mae: float


@dataclass(frozen=True, slots=True)
class CIOStatisticalCertificationReport:
    as_of: datetime
    resolved_decision_count: int
    distinct_decision_dates: int
    mean_excess_return_vs_cash: float
    mean_excess_return_vs_best_alternative: float
    positive_dollar_value_rate: float
    cumulative_dollar_value_added_vs_cash: float
    cumulative_dollar_value_added_vs_best_alternative: float
    candidate_expected_return_mae: float
    portfolio_improvement_mae: float
    expected_realized_rank_correlation: float | None
    process_outcome_counts: tuple[tuple[str, int], ...]
    segment_validation: tuple[SegmentValidation, ...]
    walk_forward: WalkForwardIntegrityReport
    gates: tuple[tuple[str, bool], ...]
    statistically_certified: bool
    performance_claim_authorized: bool = False
    policy_change_authorized: bool = False
    investment_authority: bool = False
    schema_version: str = "cio-statistical-certification-report.v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.performance_claim_authorized or self.policy_change_authorized or self.investment_authority:
            raise ValueError("statistical certification is evidence only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "resolved_decision_count": self.resolved_decision_count,
            "distinct_decision_dates": self.distinct_decision_dates,
            "mean_excess_return_vs_cash": round(self.mean_excess_return_vs_cash, 8),
            "mean_excess_return_vs_best_alternative": round(self.mean_excess_return_vs_best_alternative, 8),
            "positive_dollar_value_rate": round(self.positive_dollar_value_rate, 8),
            "cumulative_dollar_value_added_vs_cash": round(self.cumulative_dollar_value_added_vs_cash, 2),
            "cumulative_dollar_value_added_vs_best_alternative": round(self.cumulative_dollar_value_added_vs_best_alternative, 2),
            "candidate_expected_return_mae": round(self.candidate_expected_return_mae, 8),
            "portfolio_improvement_mae": round(self.portfolio_improvement_mae, 8),
            "expected_realized_rank_correlation": self.expected_realized_rank_correlation,
            "process_outcome_counts": [list(item) for item in self.process_outcome_counts],
            "segment_validation": [
                {
                    "dimension": item.dimension,
                    "value": item.value,
                    "observation_count": item.observation_count,
                    "mean_excess_return_vs_cash": round(item.mean_excess_return_vs_cash, 8),
                    "mean_excess_return_vs_best_alternative": round(item.mean_excess_return_vs_best_alternative, 8),
                    "positive_dollar_value_rate": round(item.positive_dollar_value_rate, 8),
                    "expected_return_mae": round(item.expected_return_mae, 8),
                }
                for item in self.segment_validation
            ],
            "walk_forward": {
                "observation_count": self.walk_forward.observation_count,
                "distinct_decision_dates": self.walk_forward.distinct_decision_dates,
                "asset_classes": list(self.walk_forward.asset_classes),
                "regimes": list(self.walk_forward.regimes),
                "future_knowledge_violations": list(self.walk_forward.future_knowledge_violations),
                "training_leakage_violations": list(self.walk_forward.training_leakage_violations),
                "provider_availability_violations": list(self.walk_forward.provider_availability_violations),
                "outcome_timing_violations": list(self.walk_forward.outcome_timing_violations),
                "point_in_time_passed": self.walk_forward.point_in_time_passed,
            },
            "gates": [[name, passed] for name, passed in self.gates],
            "statistically_certified": self.statistically_certified,
            "performance_claim_authorized": False,
            "policy_change_authorized": False,
            "investment_authority": False,
            "schema_version": self.schema_version,
        }


def certify_walk_forward(observations: Iterable[WalkForwardObservation]) -> WalkForwardIntegrityReport:
    values = tuple(observations)
    future: list[str] = []
    training: list[str] = []
    provider: list[str] = []
    outcomes: list[str] = []
    for item in values:
        if item.knowledge_cutoff > item.decision_as_of:
            future.append(item.identifier)
        if item.training_window_end >= item.decision_as_of:
            training.append(item.identifier)
        if item.provider_available_from > item.decision_as_of:
            provider.append(item.identifier)
        if item.outcome_observed_at <= item.decision_as_of:
            outcomes.append(item.identifier)
    return WalkForwardIntegrityReport(
        observation_count=len(values),
        distinct_decision_dates=len({item.decision_as_of.date() for item in values}),
        asset_classes=tuple(sorted({item.asset_class for item in values if item.asset_class})),
        regimes=tuple(sorted({item.regime for item in values if item.regime})),
        future_knowledge_violations=tuple(future),
        training_leakage_violations=tuple(training),
        provider_availability_violations=tuple(provider),
        outcome_timing_violations=tuple(outcomes),
        point_in_time_passed=not (future or training or provider or outcomes),
    )


def _process_quality(packet: Mapping[str, Any]) -> float:
    explanation = packet.get("explanation")
    opportunity = packet.get("opportunity")
    checks = (
        bool(packet.get("source_lineage")),
        isinstance(explanation, Mapping) and bool(explanation.get("evidence_identifiers")),
        isinstance(explanation, Mapping) and bool(explanation.get("invalidation_conditions")),
        isinstance(explanation, Mapping) and str(explanation.get("bear_case", "unavailable")) != "unavailable",
        isinstance(explanation, Mapping) and str(explanation.get("base_case", "unavailable")) != "unavailable",
        isinstance(explanation, Mapping) and str(explanation.get("bull_case", "unavailable")) != "unavailable",
        isinstance(opportunity, Mapping) and bool(opportunity.get("best_alternative_identifier")),
    )
    return sum(checks) / len(checks)


def _rank(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = (index + end - 1) / 2.0 + 1.0
        for position in range(index, end):
            ranks[ordered[position][0]] = average
        index = end
    return ranks


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    lrank, rrank = _rank(left), _rank(right)
    ml, mr = fmean(lrank), fmean(rrank)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(lrank, rrank))
    denominator = sqrt(
        sum((a - ml) ** 2 for a in lrank) * sum((b - mr) ** 2 for b in rrank)
    )
    # A fully tied expected or realized ranking contains zero ranking information; it
    # is not an error and should score neutral rather than masquerade as unavailable.
    return 0.0 if denominator <= 1e-12 else round(numerator / denominator, 8)


def _rows(pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> tuple[DecisionValidationRow, ...]:
    result: list[DecisionValidationRow] = []
    for packet, outcome in pairs:
        objective = dict(packet["objective"])
        opportunity = dict(packet["opportunity"])
        as_of = datetime.fromisoformat(str(packet["as_of"]))
        observed_at = datetime.fromisoformat(str(outcome["observed_at"]))
        if observed_at <= as_of:
            raise ValueError("decision outcome must be observed strictly after decision_as_of")
        portfolio_value = float(objective["portfolio_value"])
        realized_portfolio = float(outcome["realized_portfolio_return"])
        realized_cash = float(outcome["realized_cash_return"])
        realized_alt = float(outcome["realized_best_alternative_return"])
        realized_candidate = float(outcome["realized_candidate_return"])
        process_score = _process_quality(packet)
        good_process = process_score >= 6.0 / 7.0
        good_outcome = realized_portfolio > realized_cash and realized_portfolio > realized_alt
        classification = (
            DecisionProcessOutcomeClass.GOOD_PROCESS_GOOD_OUTCOME
            if good_process and good_outcome
            else DecisionProcessOutcomeClass.GOOD_PROCESS_BAD_OUTCOME
            if good_process
            else DecisionProcessOutcomeClass.WEAK_PROCESS_LUCKY_OUTCOME
            if good_outcome
            else DecisionProcessOutcomeClass.WEAK_PROCESS_BAD_OUTCOME
        )
        evidence = tuple(
            dict.fromkeys(
                (
                    *(str(item) for item in packet.get("source_lineage", ()) if str(item).strip()),
                    *(str(item) for item in outcome.get("evidence_identifiers", ()) if str(item).strip()),
                )
            )
        )
        result.append(
            DecisionValidationRow(
                packet_identifier=str(packet["identifier"]),
                decision_as_of=as_of,
                outcome_observed_at=observed_at,
                asset_class=str(packet.get("vehicle_asset_class", "unknown")),
                economic_exposure_class=str(packet.get("economic_exposure_class", "unknown")),
                cio_confidence=float(packet.get("cio_confidence", 0.0)),
                process_quality_score=process_score,
                expected_candidate_return=float(opportunity["candidate_expected_return"]),
                realized_candidate_return=realized_candidate,
                expected_portfolio_improvement=float(opportunity["marginal_portfolio_improvement"]),
                realized_portfolio_excess_vs_cash=realized_portfolio - realized_cash,
                realized_portfolio_excess_vs_best_alternative=realized_portfolio - realized_alt,
                expected_dollar_value_added=float(opportunity["expected_dollar_value_added"]),
                realized_dollar_value_added_vs_cash=portfolio_value * (realized_portfolio - realized_cash),
                realized_dollar_value_added_vs_best_alternative=portfolio_value * (realized_portfolio - realized_alt),
                outcome_class=classification,
                evidence_identifiers=evidence,
            )
        )
    return tuple(result)


def _segments(rows: tuple[DecisionValidationRow, ...]) -> tuple[SegmentValidation, ...]:
    dimensions = {
        "asset_class": lambda row: row.asset_class,
        "economic_exposure_class": lambda row: row.economic_exposure_class,
        "confidence_bucket": lambda row: "high" if row.cio_confidence >= 0.75 else "medium" if row.cio_confidence >= 0.50 else "low",
    }
    result: list[SegmentValidation] = []
    for dimension, getter in dimensions.items():
        for value in sorted({getter(row) for row in rows}):
            selected = tuple(row for row in rows if getter(row) == value)
            result.append(
                SegmentValidation(
                    dimension=dimension,
                    value=value,
                    observation_count=len(selected),
                    mean_excess_return_vs_cash=fmean(row.realized_portfolio_excess_vs_cash for row in selected),
                    mean_excess_return_vs_best_alternative=fmean(row.realized_portfolio_excess_vs_best_alternative for row in selected),
                    positive_dollar_value_rate=sum(row.realized_dollar_value_added_vs_best_alternative > 0.0 for row in selected) / len(selected),
                    expected_return_mae=fmean(abs(row.expected_candidate_return - row.realized_candidate_return) for row in selected),
                )
            )
    return tuple(result)


def build_cio_statistical_certification(
    *,
    decision_outcome_pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    walk_forward_observations: Iterable[WalkForwardObservation],
    as_of: datetime,
    policy: CIOStatisticalCertificationPolicy | None = None,
) -> CIOStatisticalCertificationReport:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    resolved_policy = policy or CIOStatisticalCertificationPolicy()
    pairs = tuple(decision_outcome_pairs)
    rows = _rows(pairs)
    if not rows:
        raise ValueError("statistical certification requires resolved decision outcomes")
    walk_forward = certify_walk_forward(walk_forward_observations)
    distinct_dates = len({row.decision_as_of.date() for row in rows})
    mean_cash = fmean(row.realized_portfolio_excess_vs_cash for row in rows)
    mean_alt = fmean(row.realized_portfolio_excess_vs_best_alternative for row in rows)
    positive_rate = sum(row.realized_dollar_value_added_vs_best_alternative > 0.0 for row in rows) / len(rows)
    return_mae = fmean(abs(row.expected_candidate_return - row.realized_candidate_return) for row in rows)
    improvement_errors: list[float] = []
    for (packet, outcome), row in zip(pairs, rows):
        opportunity = dict(packet["opportunity"])
        weight_change = float(opportunity["proposed_target_weight"]) - float(opportunity["current_weight"])
        realized_edge = float(outcome["realized_candidate_return"]) - float(outcome["realized_best_alternative_return"])
        improvement_errors.append(abs(row.expected_portfolio_improvement - weight_change * realized_edge))
    improvement_mae = fmean(improvement_errors)
    gates = (
        ("resolved_decision_count", len(rows) >= resolved_policy.minimum_resolved_decisions),
        ("distinct_decision_dates", distinct_dates >= resolved_policy.minimum_distinct_decision_dates),
        ("asset_class_breadth", len({row.asset_class for row in rows}) >= resolved_policy.minimum_asset_classes),
        ("regime_breadth", len(walk_forward.regimes) >= resolved_policy.minimum_regimes),
        ("point_in_time_integrity", walk_forward.point_in_time_passed),
        ("positive_dollar_value_rate", positive_rate >= resolved_policy.minimum_positive_dollar_value_rate),
        ("mean_excess_vs_cash", mean_cash > resolved_policy.minimum_mean_excess_return_vs_cash),
        ("mean_excess_vs_best_alternative", mean_alt > resolved_policy.minimum_mean_excess_return_vs_best_alternative),
        ("candidate_expected_return_error", return_mae <= resolved_policy.maximum_candidate_expected_return_mae),
        ("portfolio_improvement_error", improvement_mae <= resolved_policy.maximum_portfolio_improvement_mae),
    )
    counts = {item.value: 0 for item in DecisionProcessOutcomeClass}
    for row in rows:
        counts[row.outcome_class.value] += 1
    return CIOStatisticalCertificationReport(
        as_of=as_of,
        resolved_decision_count=len(rows),
        distinct_decision_dates=distinct_dates,
        mean_excess_return_vs_cash=mean_cash,
        mean_excess_return_vs_best_alternative=mean_alt,
        positive_dollar_value_rate=positive_rate,
        cumulative_dollar_value_added_vs_cash=sum(row.realized_dollar_value_added_vs_cash for row in rows),
        cumulative_dollar_value_added_vs_best_alternative=sum(row.realized_dollar_value_added_vs_best_alternative for row in rows),
        candidate_expected_return_mae=return_mae,
        portfolio_improvement_mae=improvement_mae,
        expected_realized_rank_correlation=_correlation(
            [row.expected_candidate_return for row in rows],
            [row.realized_candidate_return for row in rows],
        ),
        process_outcome_counts=tuple(sorted(counts.items())),
        segment_validation=_segments(rows),
        walk_forward=walk_forward,
        gates=gates,
        statistically_certified=all(passed for _name, passed in gates),
    )


__all__ = [
    "CIOStatisticalCertificationPolicy",
    "CIOStatisticalCertificationReport",
    "DecisionProcessOutcomeClass",
    "DecisionValidationRow",
    "SegmentValidation",
    "WalkForwardIntegrityReport",
    "WalkForwardObservation",
    "build_cio_statistical_certification",
    "certify_walk_forward",
]
