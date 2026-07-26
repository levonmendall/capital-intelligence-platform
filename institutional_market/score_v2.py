"""Capital Intelligence Score v2 activation contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

SCORE_V2_POLICY_VERSION = "capital-intelligence-score.v2"


class ScoreV2Status(str, Enum):
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CapitalIntelligenceScoreV2:
    status: ScoreV2Status
    policy_version: str
    preserved_prior_policy_version: str
    score: int | None
    opportunity_score: int | None
    risk_score: int | None
    resilience_score: int | None
    confidence_score: int | None
    data_quality_score: int | None
    stance: str | None
    activation_reasons: tuple[str, ...]
    personal_cio_action_affected: bool = False
    portfolio_mutation_authority: bool = False
    transaction_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "capital-intelligence-score-result.v2",
            "status": self.status.value,
            "policy_version": self.policy_version,
            "preserved_prior_policy_version": self.preserved_prior_policy_version,
            "score": self.score,
            "opportunity_score": self.opportunity_score,
            "risk_score": self.risk_score,
            "resilience_score": self.resilience_score,
            "confidence_score": self.confidence_score,
            "data_quality_score": self.data_quality_score,
            "stance": self.stance,
            "activation_reasons": list(self.activation_reasons),
            "personal_cio_action_affected": self.personal_cio_action_affected,
            "portfolio_mutation_authority": self.portfolio_mutation_authority,
            "transaction_authority": self.transaction_authority,
        }


def activate_score_v2(
    decision: Mapping[str, Any],
    approval: Mapping[str, Any],
    data_enablement: Mapping[str, Any],
    *,
    prior_policy_version: str = "capital-intelligence-score.v1",
) -> CapitalIntelligenceScoreV2:
    reasons: list[str] = []
    if not bool(approval.get("score_activation_authorized", False)):
        reasons.append("shadow approval has not authorized activation")
    if str(data_enablement.get("status")) != "authoritative":
        reasons.append("production data is not authoritative")
    opportunity = _score(decision.get("opportunity_score"))
    risk = _score(decision.get("risk_score"))
    confidence = _score(decision.get("confidence_score"))
    quality = _score(decision.get("data_quality_score"))
    stance = decision.get("stance")
    if any(value is None for value in (opportunity, risk, confidence, quality)):
        reasons.append("institutional decision does not contain complete score dimensions")
    if str(decision.get("outcome")) in {"request_more_evidence", "reject"}:
        reasons.append("committee outcome does not permit score activation")
    if reasons:
        return CapitalIntelligenceScoreV2(
            status=ScoreV2Status.UNAVAILABLE,
            policy_version=SCORE_V2_POLICY_VERSION,
            preserved_prior_policy_version=prior_policy_version,
            score=None,
            opportunity_score=opportunity,
            risk_score=risk,
            resilience_score=None if risk is None else 100 - risk,
            confidence_score=confidence,
            data_quality_score=quality,
            stance=None if stance is None else str(stance),
            activation_reasons=tuple(reasons),
        )

    assert opportunity is not None and risk is not None
    assert confidence is not None and quality is not None
    resilience = 100 - risk
    raw = round(
        opportunity * 0.45
        + resilience * 0.30
        + confidence * 0.15
        + quality * 0.10
    )
    ceiling = {
        "defensive": 49,
        "neutral": 59,
        "constructive_but_selective": 79,
    }.get(str(stance), 100)
    if str(decision.get("outcome")) == "vetoed":
        ceiling = min(ceiling, 49)
    score = max(0, min(100, raw, ceiling))
    return CapitalIntelligenceScoreV2(
        status=ScoreV2Status.ACTIVE,
        policy_version=SCORE_V2_POLICY_VERSION,
        preserved_prior_policy_version=prior_policy_version,
        score=score,
        opportunity_score=opportunity,
        risk_score=risk,
        resilience_score=resilience,
        confidence_score=confidence,
        data_quality_score=quality,
        stance=str(stance),
        activation_reasons=("production data and shadow approval gates are satisfied",),
    )


def _score(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("score dimensions must be integers between 0 and 100")
    return value
