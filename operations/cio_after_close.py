"""Research-only after-close opportunity outcome review."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from evaluation.opportunity_outcomes import SQLiteOpportunityOutcomeStore
from operations.cio_material_reassessment import (
    aware_utc,
    load_json,
    parse_clock,
    save_json,
)
from operations.equity_discovery import discover_us_equities
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
)


@dataclass(frozen=True, slots=True)
class AfterCloseLearningResult:
    state: str
    evaluated_at: datetime
    resolved_outcomes: int = 0
    tracked_symbols: int = 0
    detail: str = ""
    research_only: bool = True
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evaluated_at"] = self.evaluated_at.isoformat()
        return payload


class AfterCloseOpportunityReviewer:
    """Resolve matured outcomes once daily without current-decision authority."""

    def __init__(
        self,
        *,
        state_path: str | Path,
        outcome_store_path: str | Path,
        timezone_name: str,
        review_time: str = "13:15",
        universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
        discovery_probe: Callable[..., object] = discover_us_equities,
    ) -> None:
        self.state_path = Path(state_path).expanduser()
        self.outcome_store_path = Path(outcome_store_path).expanduser()
        self.timezone = ZoneInfo(timezone_name)
        self.review_time = parse_clock(review_time)
        self.universe_path = Path(universe_path).expanduser()
        self.discovery_probe = discovery_probe

    def run_if_due(self, *, now: datetime) -> AfterCloseLearningResult:
        timestamp = aware_utc(now, "now")
        local = timestamp.astimezone(self.timezone)
        boundary = local.replace(
            hour=self.review_time.hour,
            minute=self.review_time.minute,
            second=0,
            microsecond=0,
        )
        if local < boundary:
            return AfterCloseLearningResult(
                "not_due",
                timestamp,
                detail="The after-close research review is not due.",
            )
        operating_date = local.date().isoformat()
        state = load_json(self.state_path)
        if state.get("completed_operating_date") == operating_date:
            return AfterCloseLearningResult(
                "reused",
                timestamp,
                int(state.get("resolved_outcomes", 0) or 0),
                int(state.get("tracked_symbols", 0) or 0),
                "The research-only after-close review already completed.",
            )

        store = SQLiteOpportunityOutcomeStore(self.outcome_store_path)
        try:
            tracked = store.unresolved_symbols(as_of=timestamp)
            resolved = 0
            if tracked:
                base = load_free_paper_pilot_universe(self.universe_path)
                discovery = self.discovery_probe(
                    as_of=timestamp,
                    held_symbols=(),
                    tracked_symbols=tracked,
                    excluded_symbols=tuple(base.symbol_map),
                )
                resolved = store.resolve_due(
                    observed_at=timestamp,
                    observed_prices={
                        symbol: (price, source)
                        for symbol, price, source in discovery.observed_prices
                    },
                )
            store.verify_integrity()
        except Exception as error:
            return AfterCloseLearningResult(
                "failed",
                timestamp,
                detail=(
                    "After-close opportunity review failed closed: "
                    f"{type(error).__name__}"
                ),
            )

        save_json(
            self.state_path,
            {
                "schema_version": "after-close-opportunity-review-state.v1",
                "completed_operating_date": operating_date,
                "completed_at": timestamp.isoformat(),
                "resolved_outcomes": resolved,
                "tracked_symbols": len(tracked),
                "research_only": True,
                "execution_authority": False,
            },
        )
        return AfterCloseLearningResult(
            "completed",
            timestamp,
            resolved,
            len(tracked),
            "Research-only opportunity outcomes were evaluated after the close.",
        )


__all__ = ["AfterCloseLearningResult", "AfterCloseOpportunityReviewer"]
