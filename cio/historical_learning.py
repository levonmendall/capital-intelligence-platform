"""Governed historical-learning input for live CIO decisions.

Historical replay may only make a live decision more conservative. It cannot
create a candidate, raise expected return, increase confidence, enlarge a
position, authorize execution, or promote policy.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any, Iterable

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


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _finite(value, field_name=field_name, minimum=0.0, maximum=1.0)


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


def _item_asset_class(item: dict[str, Any]) -> CandidateAssetClass:
    raw = str(item.get("asset_class") or "").strip().lower()
    for candidate_class in CandidateAssetClass:
        if candidate_class.value == raw:
            return candidate_class
    return _historical_asset_class(
        str(item.get("symbol") or _symbol_from_identifier(item.get("candidate_identifier"))).upper()
    )


def _item_symbol(item: dict[str, Any]) -> str:
    return str(
        item.get("symbol") or _symbol_from_identifier(item.get("candidate_identifier"))
    ).strip().upper()


def _horizon_matches(item: dict[str, Any], horizon_days: int) -> bool:
    historical = item.get("decision_horizon_days")
    if isinstance(historical, bool) or not isinstance(historical, (int, float)):
        return False
    historical_days = float(historical)
    if historical_days <= 0.0:
        return False
    return min(historical_days, horizon_days) / max(historical_days, horizon_days) >= 0.50


def _regime_matches(
    item: dict[str, Any],
    *,
    macro_regime: str,
    market_regime: str,
) -> bool:
    historical_macro = str(item.get("macro_regime") or "").strip().lower()
    historical_market = str(item.get("market_regime") or "").strip().lower()
    return (
        bool(historical_macro)
        and bool(historical_market)
        and historical_macro == macro_regime.lower()
        and historical_market == market_regime.lower()
    )


def _numeric_values(items: Iterable[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for item in items:
        value = item.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number):
            values.append(number)
    return values


class HistoricalLearningStatus(str, Enum):
    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class HistoricalLearningContext:
    """Mandatory research context attached to every specialist packet.

    All adjustment fields are ceilings or multipliers at or below one. The
    context therefore cannot strengthen a live recommendation relative to the
    current point-in-time evidence package.
    """

    candidate_identifier: str
    as_of: datetime
    status: HistoricalLearningStatus
    source_manifest_identifier: str
    sample_size: int
    exact_symbol_sample_size: int
    regime_matched_sample_size: int
    horizon_matched_sample_size: int
    realized_sample_size: int
    strict_replay: bool
    support_rate: float
    abstention_rate: float
    historical_hit_rate: float
    median_historical_confidence: float
    median_historical_position_weight: float
    median_realized_return: float
    worst_realized_return: float
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
        count_fields = (
            "sample_size",
            "exact_symbol_sample_size",
            "regime_matched_sample_size",
            "horizon_matched_sample_size",
            "realized_sample_size",
        )
        for field_name in count_fields:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")
            if field_name != "sample_size" and value > self.sample_size:
                raise ValueError(f"{field_name} cannot exceed sample_size")
        if not isinstance(self.strict_replay, bool):
            raise TypeError("strict_replay must be a bool")
        for field_name in (
            "support_rate",
            "abstention_rate",
            "historical_hit_rate",
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
        object.__setattr__(
            self,
            "median_realized_return",
            _finite(
                self.median_realized_return,
                field_name="median_realized_return",
                minimum=-1.0,
            ),
        )
        object.__setattr__(
            self,
            "worst_realized_return",
            _finite(
                self.worst_realized_return,
                field_name="worst_realized_return",
                minimum=-1.0,
            ),
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
            regime_matched_sample_size=0,
            horizon_matched_sample_size=0,
            realized_sample_size=0,
            strict_replay=False,
            support_rate=0.0,
            abstention_rate=1.0,
            historical_hit_rate=0.0,
            median_historical_confidence=0.0,
            median_historical_position_weight=0.0,
            median_realized_return=0.0,
            worst_realized_return=0.0,
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
            regime_matched_sample_size=0,
            horizon_matched_sample_size=0,
            realized_sample_size=0,
            strict_replay=False,
            support_rate=0.0,
            abstention_rate=0.0,
            historical_hit_rate=0.0,
            median_historical_confidence=0.0,
            median_historical_position_weight=0.0,
            median_realized_return=0.0,
            worst_realized_return=0.0,
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
            "regime_matched_sample_size": self.regime_matched_sample_size,
            "horizon_matched_sample_size": self.horizon_matched_sample_size,
            "realized_sample_size": self.realized_sample_size,
            "strict_replay": self.strict_replay,
            "support_rate": self.support_rate,
            "abstention_rate": self.abstention_rate,
            "historical_hit_rate": self.historical_hit_rate,
            "median_historical_confidence": self.median_historical_confidence,
            "median_historical_position_weight": self.median_historical_position_weight,
            "median_realized_return": self.median_realized_return,
            "worst_realized_return": self.worst_realized_return,
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
        return cls(
            root / "manifests" / "latest-canonical-replay.json",
            minimum_sample_size=minimum,
        )

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
            if not isinstance(values, list):
                continue
            for raw_item in values:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item.setdefault("macro_regime", cutoff.get("macro_regime"))
                all_decisions.append(item)
        symbol = candidate.instrument.symbol.upper()
        asset_class = candidate.instrument.asset_class
        exact = [item for item in all_decisions if _item_symbol(item) == symbol]
        comparable = [
            item for item in all_decisions if _item_asset_class(item) is asset_class
        ]
        exact_horizon = [
            item
            for item in exact
            if _horizon_matches(item, candidate.decision_horizon_days)
        ]
        exact_regime_horizon = [
            item
            for item in exact_horizon
            if _regime_matches(
                item,
                macro_regime=macro_regime,
                market_regime=market_regime,
            )
        ]
        asset_horizon = [
            item
            for item in comparable
            if _horizon_matches(item, candidate.decision_horizon_days)
        ]
        asset_regime_horizon = [
            item
            for item in asset_horizon
            if _regime_matches(
                item,
                macro_regime=macro_regime,
                market_regime=market_regime,
            )
        ]
        pools = (
            ("exact symbol, regime, and horizon", exact_regime_horizon),
            ("exact symbol and horizon", exact_horizon),
            ("asset class, regime, and horizon", asset_regime_horizon),
            ("exact symbol", exact),
            ("asset class and horizon", asset_horizon),
            ("asset class", comparable),
        )
        basis = "none"
        selected: list[dict[str, Any]] = []
        for label, pool in pools:
            if len(pool) >= self.minimum_sample_size:
                basis, selected = label, pool
                break
        if not selected:
            nonempty = [(label, pool) for label, pool in pools if pool]
            if nonempty:
                basis, selected = max(nonempty, key=lambda item: len(item[1]))
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
        confidence_values = _numeric_values(selected, "final_confidence")
        weight_values = _numeric_values(selected, "recommended_position_weight")
        realized_values = _numeric_values(selected, "realized_return_to_next_cutoff")
        support_rate = sum(action in _SUPPORTIVE_ACTIONS for action in actions) / len(selected)
        abstention_rate = sum(action in _ABSTENTION_ACTIONS for action in actions) / len(selected)
        historical_confidence = median(confidence_values) if confidence_values else 0.0
        historical_weight = median(weight_values) if weight_values else 0.0
        hit_rate = (
            sum(value > 0.0 for value in realized_values) / len(realized_values)
            if realized_values
            else 0.0
        )
        median_realized = median(realized_values) if realized_values else 0.0
        worst_realized = min(realized_values) if realized_values else 0.0
        exact_count = sum(_item_symbol(item) == symbol for item in selected)
        regime_count = sum(
            _regime_matches(
                item,
                macro_regime=macro_regime,
                market_regime=market_regime,
            )
            for item in selected
        )
        horizon_count = sum(
            _horizon_matches(item, candidate.decision_horizon_days)
            for item in selected
        )
        strict_replay = bool(payload.get("strict_only", False))
        minimum_realized = min(3, self.minimum_sample_size)
        limited = (
            len(selected) < self.minimum_sample_size
            or exact_count == 0
            or len(realized_values) < minimum_realized
            or basis in {"asset class", "asset class and horizon"}
        )
        status = (
            HistoricalLearningStatus.LIMITED
            if limited
            else HistoricalLearningStatus.AVAILABLE
        )
        sample_scale = min(1.0, len(selected) / max(self.minimum_sample_size * 2, 1))
        sample_factor = 0.70 + 0.30 * sample_scale
        quality_factor = 1.0 if strict_replay else 0.90
        support_factor = 0.75 + 0.25 * support_rate
        confidence_factor = 0.75 + 0.25 * historical_confidence
        outcome_factor = 0.75 if not realized_values else 0.65 + 0.35 * hit_rate
        return_factor = min(1.0, max(0.60, 1.0 + min(0.0, median_realized) * 2.0))
        tail_factor = min(1.0, max(0.55, 1.0 + min(0.0, worst_realized)))
        regime_factor = 0.85 + 0.15 * (regime_count / len(selected))
        horizon_factor = 0.85 + 0.15 * (horizon_count / len(selected))
        size_multiplier = min(
            1.0,
            max(
                0.35,
                sample_factor
                * quality_factor
                * support_factor
                * confidence_factor
                * outcome_factor
                * return_factor
                * tail_factor
                * regime_factor
                * horizon_factor,
            ),
        )
        if limited:
            size_multiplier = min(size_multiplier, 0.65)
        confidence_ceiling = min(
            0.92 if strict_replay else 0.82,
            0.55
            + 0.20 * historical_confidence
            + 0.15 * hit_rate
            + 0.10 * sample_scale,
        )
        if limited:
            confidence_ceiling = min(confidence_ceiling, 0.70)
        limitations = [
            "Historical replay is research evidence and cannot override current point-in-time evidence.",
            "Historical learning may only reduce live confidence and position size.",
            "Historical outcomes do not guarantee future investment results.",
        ]
        if not strict_replay:
            limitations.append(
                "The current replay includes clearly labeled non-strict public research bridges."
            )
        if exact_count == 0:
            limitations.append(
                "No exact-symbol history met the selection gate; asset-class comparables were used."
            )
        if regime_count == 0:
            limitations.append(
                "No comparable observation matched both the current macro and market regimes."
            )
        if len(realized_values) < minimum_realized:
            limitations.append(
                "Realized next-cutoff outcome coverage is insufficient for full calibration."
            )
        source_identifier = f"canonical-historical-replay:{generated_at.isoformat()}"
        realized_summary = (
            f"realized n={len(realized_values)}, hit={hit_rate:.1%}, "
            f"median={median_realized:+.2%}, worst={worst_realized:+.2%}"
            if realized_values
            else "realized outcomes unavailable"
        )
        summary = (
            f"Historical learning used {len(selected)} {basis} decisions "
            f"(exact={exact_count}, regime={regime_count}, horizon={horizon_count}); "
            f"support={support_rate:.1%}, abstention={abstention_rate:.1%}, "
            f"median confidence={historical_confidence:.1%}, {realized_summary}. "
            f"Live size is capped at {size_multiplier:.1%} of the otherwise supported target "
            f"and confidence cannot exceed {confidence_ceiling:.1%}. Current evidence remains controlling."
        )
        return HistoricalLearningContext(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            status=status,
            source_manifest_identifier=source_identifier,
            sample_size=len(selected),
            exact_symbol_sample_size=exact_count,
            regime_matched_sample_size=regime_count,
            horizon_matched_sample_size=horizon_count,
            realized_sample_size=len(realized_values),
            strict_replay=strict_replay,
            support_rate=support_rate,
            abstention_rate=abstention_rate,
            historical_hit_rate=hit_rate,
            median_historical_confidence=historical_confidence,
            median_historical_position_weight=historical_weight,
            median_realized_return=median_realized,
            worst_realized_return=worst_realized,
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
