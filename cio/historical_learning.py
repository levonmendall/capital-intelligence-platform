"""Governed historical-learning input for live CIO decisions.

Historical replay may only make a live decision more conservative.  It cannot
create a candidate, raise expected return, increase confidence, enlarge a
position, authorize execution, or promote policy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any

from cio.models import CandidateAssetClass, CandidateDecisionRecord

UTC = timezone.utc
_DEFAULT_ETFS = frozenset(
    {
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "EFA",
        "EEM",
        "TLT",
        "IEF",
        "LQD",
        "HYG",
        "GLD",
        "SLV",
        "USO",
        "VNQ",
    }
)
_SUPPORTIVE_ACTIONS = frozenset({"buy", "increase", "hold", "no_material_change"})
_ABSTENTION_ACTIONS = frozenset(
    {"watch", "insufficient_evidence", "no_superior_opportunity"}
)


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return round(normalized, 8)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _symbol_from_identifier(value: object) -> str:
    text = str(value or "").strip().upper()
    return text.rsplit(":", 1)[-1]


def _historical_asset_class(symbol: str) -> CandidateAssetClass:
    if "-USD" in symbol:
        return CandidateAssetClass.CRYPTO
    if symbol in _DEFAULT_ETFS:
        return CandidateAssetClass.US_ETF
    return CandidateAssetClass.US_EQUITY


class HistoricalLearningStatus(str, Enum):
    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class HistoricalLearningContext:
    """Mandatory research context attached to every specialist packet.

    All adjustment fields are ceilings or multipliers at or below one.  The
    context therefore cannot strengthen a live recommendation relative to the
    current point-in-time evidence package.
    """

    candidate_identifier: str
    as_of: datetime
    status: HistoricalLearningStatus
    source_manifest_identifier: str
    sample_size: int
    exact_symbol_sample_size: int
    strict_replay: bool
    support_rate: float
    abstention_rate: float
    median_historical_confidence: float
    median_historical_position_weight: float
    position_size_multiplier: float
    confidence_ceiling: float
    summary: str
    limitations: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    subordinate_to_current_evidence: bool = True
    may_increase_expected_return: bool = False
    may_increase_confidence: bool = False
    may_increase_position_size: bool = False
    execution_authorized: bool = False
    policy_promotion_authorized: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_identifier",
            "source_manifest_identifier",
            "summary",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.status, HistoricalLearningStatus):
            raise TypeError("status must be a HistoricalLearningStatus")
        for field_name in ("sample_size", "exact_symbol_sample_size"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.exact_symbol_sample_size > self.sample_size:
            raise ValueError("exact_symbol_sample_size cannot exceed sample_size")
        if not isinstance(self.strict_replay, bool):
            raise TypeError("strict_replay must be a bool")
        for field_name in (
            "support_rate",
            "abstention_rate",
            "median_historical_confidence",
            "median_historical_position_weight",
            "position_size_multiplier",
            "confidence_ceiling",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("limitations", "evidence_identifiers"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
            if len(value) != len(set(value)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        for field_name in (
            "subordinate_to_current_evidence",
            "may_increase_expected_return",
            "may_increase_confidence",
            "may_increase_position_size",
            "execution_authorized",
            "policy_promotion_authorized",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        if not self.subordinate_to_current_evidence:
            raise ValueError("historical learning must remain subordinate to current evidence")
        if any(
            (
                self.may_increase_expected_return,
                self.may_increase_confidence,
                self.may_increase_position_size,
                self.execution_authorized,
                self.policy_promotion_authorized,
            )
        ):
            raise ValueError(
                "historical learning cannot strengthen forecasts, size, authority, or policy"
            )

    @classmethod
    def unavailable(
        cls,
        *,
        candidate_identifier: str,
        as_of: datetime,
        reason: str = "No governed historical replay manifest was available at the decision timestamp.",
    ) -> "HistoricalLearningContext":
        return cls(
            candidate_identifier=candidate_identifier,
            as_of=as_of,
            status=HistoricalLearningStatus.UNAVAILABLE,
            source_manifest_identifier="historical-learning:unavailable",
            sample_size=0,
            exact_symbol_sample_size=0,
            strict_replay=False,
            support_rate=0.0,
            abstention_rate=1.0,
            median_historical_confidence=0.0,
            median_historical_position_weight=0.0,
            position_size_multiplier=0.50,
            confidence_ceiling=0.65,
            summary=reason,
            limitations=(reason,),
            evidence_identifiers=("historical-learning:unavailable",),
        )

    @classmethod
    def not_applicable(
        cls,
        *,
        candidate_identifier: str,
        as_of: datetime,
        reason: str,
    ) -> "HistoricalLearningContext":
        return cls(
            candidate_identifier=candidate_identifier,
            as_of=as_of,
            status=HistoricalLearningStatus.NOT_APPLICABLE,
            source_manifest_identifier="historical-learning:not-applicable",
            sample_size=0,
            exact_symbol_sample_size=0,
            strict_replay=False,
            support_rate=0.0,
            abstention_rate=0.0,
            median_historical_confidence=0.0,
            median_historical_position_weight=0.0,
            position_size_multiplier=1.0,
            confidence_ceiling=1.0,
            summary=reason,
            limitations=(reason,),
            evidence_identifiers=("historical-learning:not-applicable",),
        )

    def validate_for(self, candidate_identifier: str, *, completed_at: datetime) -> None:
        if self.candidate_identifier != candidate_identifier:
            raise ValueError("historical learning does not match the candidate")
        _aware(completed_at, field_name="completed_at")
        if self.as_of > completed_at:
            raise ValueError("historical learning cannot postdate specialist completion")

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "as_of": self.as_of.isoformat(),
            "status": self.status.value,
            "source_manifest_identifier": self.source_manifest_identifier,
            "sample_size": self.sample_size,
            "exact_symbol_sample_size": self.exact_symbol_sample_size,
            "strict_replay": self.strict_replay,
            "support_rate": self.support_rate,
            "abstention_rate": self.abstention_rate,
            "median_historical_confidence": self.median_historical_confidence,
            "median_historical_position_weight": self.median_historical_position_weight,
            "position_size_multiplier": self.position_size_multiplier,
            "confidence_ceiling": self.confidence_ceiling,
            "summary": self.summary,
            "limitations": list(self.limitations),
            "evidence_identifiers": list(self.evidence_identifiers),
            "subordinate_to_current_evidence": self.subordinate_to_current_evidence,
            "may_increase_expected_return": self.may_increase_expected_return,
            "may_increase_confidence": self.may_increase_confidence,
            "may_increase_position_size": self.may_increase_position_size,
            "execution_authorized": self.execution_authorized,
            "policy_promotion_authorized": self.policy_promotion_authorized,
        }


class HistoricalLearningResolver:
    """Resolve a conservative live-decision context from canonical replay output."""

    def __init__(
        self,
        manifest_path: str | Path,
        *,
        minimum_sample_size: int = 6,
    ) -> None:
        if minimum_sample_size < 1:
            raise ValueError("minimum_sample_size must be positive")
        self.manifest_path = Path(manifest_path)
        self.minimum_sample_size = minimum_sample_size

    @classmethod
    def from_environment(cls) -> "HistoricalLearningResolver":
        root = Path(
            os.getenv(
                "CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR",
                "database/historical_replay",
            )
        )
        minimum = int(
            os.getenv(
                "CAPITAL_INTELLIGENCE_HISTORICAL_LEARNING_MINIMUM_SAMPLE",
                "6",
            )
        )
        return cls(root / "manifests" / "latest-canonical-replay.json", minimum_sample_size=minimum)

    def resolve(
        self,
        candidate: CandidateDecisionRecord,
        *,
        as_of: datetime,
        macro_regime: str,
        market_regime: str,
    ) -> HistoricalLearningContext:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        _aware(as_of, field_name="as_of")
        macro_regime = _required_text(macro_regime, field_name="macro_regime")
        market_regime = _required_text(market_regime, field_name="market_regime")
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason=f"Governed historical learning is unavailable: {type(error).__name__}.",
            )
        if not isinstance(payload, dict):
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason="Governed historical learning manifest is not an object.",
            )
        generated_at = _parse_timestamp(payload.get("generated_at"))
        if generated_at is None:
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason="Governed historical learning manifest lacks a valid generation timestamp.",
            )
        if generated_at > as_of.astimezone(UTC):
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason="Historical learning was generated after the decision timestamp and was excluded.",
            )
        raw_cutoffs = payload.get("decisions", [])
        if not isinstance(raw_cutoffs, list):
            raw_cutoffs = []
        all_decisions: list[dict[str, Any]] = []
        for cutoff in raw_cutoffs:
            if not isinstance(cutoff, dict) or cutoff.get("state") != "completed":
                continue
            values = cutoff.get("decisions", [])
            if isinstance(values, list):
                all_decisions.extend(item for item in values if isinstance(item, dict))
        symbol = candidate.instrument.symbol.upper()
        asset_class = candidate.instrument.asset_class
        exact = [
            item
            for item in all_decisions
            if _symbol_from_identifier(item.get("candidate_identifier")) == symbol
        ]
        comparable = [
            item
            for item in all_decisions
            if _historical_asset_class(
                _symbol_from_identifier(item.get("candidate_identifier"))
            )
            is asset_class
        ]
        selected = exact if len(exact) >= self.minimum_sample_size else comparable
        if not selected:
            return HistoricalLearningContext.unavailable(
                candidate_identifier=candidate.identifier,
                as_of=as_of,
                reason=(
                    "Historical replay is present, but no comparable asset-class decisions "
                    "were available for this candidate."
                ),
            )
        actions = [str(item.get("action", "")).strip().lower() for item in selected]
        confidence_values = [
            float(item["final_confidence"])
            for item in selected
            if isinstance(item.get("final_confidence"), (int, float))
        ]
        weight_values = [
            float(item["recommended_position_weight"])
            for item in selected
            if isinstance(item.get("recommended_position_weight"), (int, float))
        ]
        support_rate = sum(action in _SUPPORTIVE_ACTIONS for action in actions) / len(selected)
        abstention_rate = sum(action in _ABSTENTION_ACTIONS for action in actions) / len(selected)
        historical_confidence = median(confidence_values) if confidence_values else 0.0
        historical_weight = median(weight_values) if weight_values else 0.0
        strict_replay = bool(payload.get("strict_only", False))
        exact_count = len(exact)
        limited = len(selected) < self.minimum_sample_size or exact_count == 0
        status = (
            HistoricalLearningStatus.LIMITED
            if limited
            else HistoricalLearningStatus.AVAILABLE
        )
        sample_scale = min(1.0, len(selected) / max(self.minimum_sample_size * 2, 1))
        quality_scale = 1.0 if strict_replay else 0.90
        support_scale = 0.75 + 0.25 * support_rate
        confidence_scale = 0.65 + 0.35 * historical_confidence
        size_multiplier = min(
            1.0,
            max(0.35, sample_scale * support_scale * confidence_scale * quality_scale),
        )
        if limited:
            size_multiplier = min(size_multiplier, 0.65)
        confidence_ceiling = min(
            0.90 if strict_replay else 0.80,
            0.55 + 0.35 * historical_confidence + 0.10 * sample_scale,
        )
        if limited:
            confidence_ceiling = min(confidence_ceiling, 0.70)
        limitations = [
            "Historical replay is research evidence and cannot override current point-in-time evidence.",
            "Replay action frequency is not a guarantee of realized investment performance.",
            "Historical learning may only reduce live confidence and position size.",
        ]
        if not strict_replay:
            limitations.append(
                "The current replay includes clearly labeled non-strict public research bridges."
            )
        if exact_count == 0:
            limitations.append(
                "No exact-symbol history met the minimum sample; asset-class comparables were used."
            )
        source_identifier = f"canonical-historical-replay:{generated_at.isoformat()}"
        summary = (
            f"Historical learning used {len(selected)} comparable canonical decisions "
            f"({exact_count} exact-symbol), support={support_rate:.1%}, "
            f"abstention={abstention_rate:.1%}, median confidence={historical_confidence:.1%}; "
            f"live size is capped at {size_multiplier:.1%} of the otherwise supported target "
            f"and confidence cannot exceed {confidence_ceiling:.1%}. Current evidence remains controlling."
        )
        return HistoricalLearningContext(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            status=status,
            source_manifest_identifier=source_identifier,
            sample_size=len(selected),
            exact_symbol_sample_size=exact_count,
            strict_replay=strict_replay,
            support_rate=support_rate,
            abstention_rate=abstention_rate,
            median_historical_confidence=historical_confidence,
            median_historical_position_weight=historical_weight,
            position_size_multiplier=size_multiplier,
            confidence_ceiling=confidence_ceiling,
            summary=summary,
            limitations=tuple(limitations),
            evidence_identifiers=(source_identifier,),
        )


__all__ = [
    "HistoricalLearningContext",
    "HistoricalLearningResolver",
    "HistoricalLearningStatus",
]
