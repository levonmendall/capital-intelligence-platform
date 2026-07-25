"""Pure view-model helpers for the daily Capital Intelligence screen."""

from __future__ import annotations

from dataclasses import dataclass

from application import DailyCapitalIntelligenceSnapshot, DailySnapshotRecord


@dataclass(frozen=True, slots=True)
class DailyIntelligenceView:
    score: int
    score_label: str
    score_change: str
    environment: str
    risk: str
    committee: str
    portfolio_impact: str
    what_changed: str
    status: str
    should_alert: bool
    considerations: tuple[str, ...]
    history: tuple[tuple[str, int], ...]
    replay_identifiers: tuple[str, ...]


def build_daily_intelligence_view(
    snapshot: DailyCapitalIntelligenceSnapshot,
    history: tuple[DailySnapshotRecord, ...] = (),
) -> DailyIntelligenceView:
    if not isinstance(snapshot, DailyCapitalIntelligenceSnapshot):
        raise TypeError("snapshot must be a DailyCapitalIntelligenceSnapshot")
    if not isinstance(history, tuple) or not all(
        isinstance(item, DailySnapshotRecord) for item in history
    ):
        raise TypeError("history must contain DailySnapshotRecord values")
    delta = snapshot.score_delta
    score_change = (
        "No prior score"
        if delta is None
        else "Unchanged"
        if delta == 0
        else f"{delta:+d} since prior snapshot"
    )
    ordered_history = tuple(
        (record.as_of.isoformat(), record.score)
        for record in reversed(history)
    )
    return DailyIntelligenceView(
        score=snapshot.score.score,
        score_label=snapshot.score.label,
        score_change=score_change,
        environment=snapshot.score.environment,
        risk=snapshot.score.risk,
        committee=snapshot.score.committee,
        portfolio_impact=snapshot.score.portfolio_impact,
        what_changed=snapshot.change_summary,
        status=snapshot.status.value,
        should_alert=snapshot.should_alert,
        considerations=snapshot.score.considerations,
        history=ordered_history,
        replay_identifiers=snapshot.replay_identifiers,
    )


__all__ = ["DailyIntelligenceView", "build_daily_intelligence_view"]
