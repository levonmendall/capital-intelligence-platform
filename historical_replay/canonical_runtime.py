"""Production-scale single-pass Canonical CIO historical replay runtime.

The reference canonical adapter is intentionally simple and correct, but reopening and
re-decompressing every historical partition for each cutoff makes a ten-year monthly
run scale as O(cutoffs × archive). This runtime scans the relevant archive once, sorts
by historical availability, and advances a monotonic point-in-time cursor.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from .canonical import CanonicalHistoricalReplayEngine, ReplayPortfolioState
from .models import HistoricalRecord, iso_timestamp
from .replay import replay_dates

UTC = timezone.utc
_REQUIRED_MACRO_DATASETS = frozenset(
    {
        "series.fedfunds",
        "series.t10y2y",
        "series.vixcls",
    }
)


def _decision_time(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59), tzinfo=UTC)


def _replay_relevant(record: HistoricalRecord) -> bool:
    """Keep only evidence currently consumed by the canonical context builder."""

    return "close" in record.payload or record.dataset in _REQUIRED_MACRO_DATASETS


class EfficientCanonicalHistoricalReplayEngine(CanonicalHistoricalReplayEngine):
    """Run canonical historical cutoffs from one availability-ordered archive scan."""

    def run(
        self,
        *,
        start: date,
        end: date,
        cadence: str = "monthly",
        strict_only: bool = False,
        initial_portfolio_value: float = 250_000.0,
    ) -> dict[str, Any]:
        if initial_portfolio_value <= 0.0:
            raise ValueError("initial_portfolio_value must be positive")
        if start > end:
            raise ValueError("start must not be after end")

        relevant = sorted(
            (
                record
                for record in self.store.iter_records(strict_only=strict_only)
                if _replay_relevant(record)
            ),
            key=lambda item: (item.available_datetime, item.record_id),
        )
        price_record_count = sum(1 for item in relevant if "close" in item.payload)
        macro_record_count = len(relevant) - price_record_count

        state = ReplayPortfolioState(value=float(initial_portfolio_value))
        decisions: list[dict[str, Any]] = []
        completed = blocked = 0
        visible: list[HistoricalRecord] = []
        cursor = 0

        for cutoff_date in replay_dates(start, end, cadence):
            cutoff = _decision_time(cutoff_date)
            while (
                cursor < len(relevant)
                and relevant[cursor].available_datetime <= cutoff
            ):
                visible.append(relevant[cursor])
                cursor += 1
            records = tuple(visible)
            try:
                candidates, contexts, opportunity, portfolio, prices = (
                    self.builder.build(
                        records=records,
                        cutoff=cutoff,
                        state=state,
                        strict_only=strict_only,
                    )
                )
                if not candidates:
                    raise RuntimeError(
                        "no historical candidates satisfy the point-in-time coverage gate"
                    )
                result = self.cycle.run(
                    identifier=f"historical-canonical-cycle:{cutoff_date}",
                    candidates=candidates,
                    opportunity_context=opportunity,
                    specialist_contexts=contexts,
                    portfolio=portfolio,
                    code_version="historical-canonical-replay.v2",
                )
                candidate_map = {item.identifier: item for item in candidates}
                context_map = {
                    item.candidate_identifier: item for item in contexts
                }
                decision_payloads = [
                    self._decision_payload(
                        item,
                        candidate=candidate_map.get(item.candidate_identifier),
                        context=context_map.get(item.candidate_identifier),
                    )
                    for item in result.decisions
                ]
                state.apply_construction(result.construction)
                state.previous_prices.update(prices)
                construction = result.construction
                payload = {
                    "cutoff": iso_timestamp(cutoff),
                    "state": "completed",
                    "canonical_cio_invoked": True,
                    "candidate_count": len(candidates),
                    "decision_count": len(result.decisions),
                    "visible_record_count": len(records),
                    "decisions": decision_payloads,
                    "prices": dict(prices),
                    "macro_regime": (
                        contexts[0].macro.regime if contexts else "unavailable"
                    ),
                    "construction": (
                        None
                        if construction is None
                        else {
                            "status": construction.status.value,
                            "target_cash_weight": construction.target_cash_weight,
                            "target_weights": dict(construction.target_weights),
                            "turnover": construction.turnover,
                            "estimated_cost_return": construction.estimated_cost_return,
                            "blocks": list(construction.blocks),
                        }
                    ),
                    "portfolio_value": state.value,
                    "portfolio_weights": dict(state.weights),
                    "cash_weight": state.cash_weight,
                }
                completed += 1
            except Exception as error:
                payload = {
                    "cutoff": iso_timestamp(cutoff),
                    "state": "blocked",
                    "canonical_cio_invoked": False,
                    "visible_record_count": len(records),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "portfolio_value": state.value,
                    "portfolio_weights": dict(state.weights),
                    "cash_weight": state.cash_weight,
                }
                blocked += 1
            decisions.append(payload)

        self._attach_realized_outcomes(decisions)
        realized_outcome_count = sum(
            1
            for cutoff in decisions
            for decision in cutoff.get("decisions", [])
            if isinstance(decision, dict)
            and isinstance(
                decision.get("realized_return_to_next_cutoff"),
                (int, float),
            )
        )
        report = {
            "schema_version": "canonical-historical-replay.v2",
            "runtime_version": "single-pass-availability-cursor.v2",
            "learning_context_schema_version": "governed-historical-learning.v1",
            "generated_at": iso_timestamp(datetime.now(tz=UTC)),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "cadence": cadence,
            "strict_only": strict_only,
            "strict_replay": strict_only,
            "research_only": True,
            "canonical_cio_available": True,
            "canonical_cio_invoked_count": completed,
            "blocked_cutoff_count": blocked,
            "decision_cutoff_count": len(decisions),
            "archive_scan_count": 1,
            "relevant_record_count": len(relevant),
            "price_record_count": price_record_count,
            "macro_record_count": macro_record_count,
            "realized_outcome_count": realized_outcome_count,
            "initial_portfolio_value": float(initial_portfolio_value),
            "ending_portfolio_value": state.value,
            "ending_weights": dict(state.weights),
            "ending_cash_weight": state.cash_weight,
            "decisions": decisions,
            "execution_authorized": False,
            "paper_execution_authorized": False,
            "real_money_authorized": False,
            "policy_promotion_authorized": False,
            "performance_claims_authorized": False,
        }
        self.store.write_manifest("latest-canonical-replay", report)
        return report


__all__ = ["EfficientCanonicalHistoricalReplayEngine"]
