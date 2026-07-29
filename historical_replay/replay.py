"""Walk-forward, look-ahead-safe shadow replay.

This does not invoke or replace the canonical CIO. It creates research evidence only and
keeps policy promotion, execution, real-money authority, and performance claims disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .features import event_features, market_features
from .models import iso_timestamp
from .store import HistoricalStore

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    cutoff: str
    selected_assets: tuple[str, ...]
    weights: dict[str, float]
    feature_snapshot: dict[str, dict[str, Any]]
    event_counts: dict[str, int]
    strict_replay: bool
    research_only: bool = True
    canonical_cio_invoked: bool = False
    execution_authorized: bool = False
    real_money_authorized: bool = False
    performance_claims_authorized: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "cutoff": self.cutoff,
            "selected_assets": list(self.selected_assets),
            "weights": self.weights,
            "feature_snapshot": self.feature_snapshot,
            "event_counts": self.event_counts,
            "strict_replay": self.strict_replay,
            "research_only": self.research_only,
            "canonical_cio_invoked": self.canonical_cio_invoked,
            "execution_authorized": self.execution_authorized,
            "real_money_authorized": self.real_money_authorized,
            "performance_claims_authorized": self.performance_claims_authorized,
        }


def replay_dates(start: date, end: date, cadence: str) -> tuple[date, ...]:
    if cadence not in {"weekly", "monthly"}:
        raise ValueError("cadence must be weekly or monthly")
    dates: list[date] = []
    cursor = start
    if cadence == "weekly":
        cursor += timedelta(days=(4 - cursor.weekday()) % 7)
        while cursor <= end:
            dates.append(cursor)
            cursor += timedelta(days=7)
    else:
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            next_month = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
            month_end = next_month - timedelta(days=1)
            if month_end >= start and month_end <= end:
                dates.append(month_end)
            cursor = next_month
    return tuple(dates)


class ShadowReplayEngine:
    def __init__(self, store: HistoricalStore) -> None:
        self.store = store

    def decision(self, *, cutoff: date, strict_only: bool = True, top_n: int = 3) -> ShadowDecision:
        cutoff_text = iso_timestamp(cutoff)
        records = tuple(self.store.iter_records(available_before=cutoff_text, strict_only=strict_only))
        features = market_features(records, cutoff=cutoff_text)
        ranked = sorted(
            features,
            key=lambda symbol: (
                features[symbol]["momentum"] > 0,
                features[symbol]["momentum"] / max(features[symbol]["annualized_volatility"], 0.05),
            ),
            reverse=True,
        )
        selected = tuple(symbol for symbol in ranked if features[symbol]["momentum"] > 0)[:top_n]
        weights = ({symbol: 1.0 / len(selected) for symbol in selected} if selected else {"CASH": 1.0})
        return ShadowDecision(
            cutoff=cutoff_text,
            selected_assets=selected,
            weights=weights,
            feature_snapshot={symbol: features[symbol] for symbol in selected},
            event_counts=event_features(records, cutoff=cutoff_text),
            strict_replay=strict_only,
        )

    def run(self, *, start: date, end: date, cadence: str = "monthly", strict_only: bool = True) -> dict[str, Any]:
        decisions = [self.decision(cutoff=cutoff, strict_only=strict_only).as_dict() for cutoff in replay_dates(start, end, cadence)]
        report = {
            "generated_at": iso_timestamp(datetime.now(tz=UTC)),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "cadence": cadence,
            "strict_only": strict_only,
            "decision_count": len(decisions),
            "decisions": decisions,
            "research_only": True,
            "canonical_cio_invoked": False,
            "policy_promotion_authorized": False,
            "execution_authorized": False,
            "real_money_authorized": False,
            "performance_claims_authorized": False,
        }
        self.store.write_manifest("latest-shadow-replay", report)
        return report
