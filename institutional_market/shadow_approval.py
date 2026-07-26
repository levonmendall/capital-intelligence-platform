"""Formal review and approval gate for institutional shadow mode."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ShadowApprovalStatus(str, Enum):
    APPROVED = "approved"
    EXTEND_SHADOW = "extend_shadow"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ShadowApprovalPolicy:
    version: str = "shadow-approval-policy.v1"
    minimum_observations: int = 20
    maximum_turnover_rate: float = 0.35
    maximum_missed_deterioration_rate: float = 0.20
    maximum_false_alarm_rate: float = 0.30
    minimum_median_confidence: int = 50
    minimum_data_quality: int = 60
    require_leakage_free: bool = True
    require_authoritative_production_data: bool = True


@dataclass(frozen=True, slots=True)
class ShadowApprovalDecision:
    policy_version: str
    status: ShadowApprovalStatus
    reasons: tuple[str, ...]
    score_activation_authorized: bool
    weights_changed: bool = False
    committee_policy_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "shadow-approval-decision.v1",
            "policy_version": self.policy_version,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "score_activation_authorized": self.score_activation_authorized,
            "weights_changed": self.weights_changed,
            "committee_policy_changed": self.committee_policy_changed,
        }


def review_shadow_mode(
    report: Mapping[str, Any],
    *,
    production_data_authoritative: bool,
    policy: ShadowApprovalPolicy = ShadowApprovalPolicy(),
) -> ShadowApprovalDecision:
    count = int(report.get("observation_count", 0))
    available = int(report.get("available_count", 0))
    turnover = float(report.get("turnover_rate", 1.0))
    missed = int(report.get("missed_deterioration_count", 0))
    timely = int(report.get("timely_deterioration_count", 0))
    false_alarms = int(report.get("false_alarm_count", 0))
    confidence = report.get("median_confidence")
    quality = report.get("minimum_data_quality")
    leakage_free = bool(report.get("leakage_free", False))
    weights_optimized = bool(report.get("weights_optimized_for_return", False))

    hard_rejections: list[str] = []
    if policy.require_leakage_free and not leakage_free:
        hard_rejections.append("look-ahead leakage is present")
    if weights_optimized:
        hard_rejections.append("weights were optimized for historical return")
    if hard_rejections:
        return ShadowApprovalDecision(
            policy_version=policy.version,
            status=ShadowApprovalStatus.REJECTED,
            reasons=tuple(hard_rejections),
            score_activation_authorized=False,
        )

    reasons: list[str] = []
    if count < policy.minimum_observations:
        reasons.append("shadow history is shorter than the policy minimum")
    if available < policy.minimum_observations:
        reasons.append("available decision history is shorter than the policy minimum")
    if turnover > policy.maximum_turnover_rate:
        reasons.append("stance turnover exceeds the policy maximum")
    deterioration_total = timely + missed
    missed_rate = missed / deterioration_total if deterioration_total else 0.0
    if missed_rate > policy.maximum_missed_deterioration_rate:
        reasons.append("missed deterioration rate exceeds the policy maximum")
    false_alarm_rate = false_alarms / available if available else 1.0
    if false_alarm_rate > policy.maximum_false_alarm_rate:
        reasons.append("false defensive alarm rate exceeds the policy maximum")
    if confidence is None or int(confidence) < policy.minimum_median_confidence:
        reasons.append("median confidence is below the policy minimum")
    if quality is None or int(quality) < policy.minimum_data_quality:
        reasons.append("minimum data quality is below the policy minimum")
    if policy.require_authoritative_production_data and not production_data_authoritative:
        reasons.append("production data has not cleared the authoritative gate")

    status = ShadowApprovalStatus.APPROVED if not reasons else ShadowApprovalStatus.EXTEND_SHADOW
    return ShadowApprovalDecision(
        policy_version=policy.version,
        status=status,
        reasons=tuple(reasons),
        score_activation_authorized=status is ShadowApprovalStatus.APPROVED,
    )
