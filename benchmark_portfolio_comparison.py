"""Read-only benchmark comparison for the canonical paper portfolio.

The comparison consumes existing point-in-time paper-operation evidence. It is a
measurement surface only: it cannot nominate an asset, alter a threshold, affect
CIO qualification, size a position, construct a portfolio, or authorize execution.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from evaluation import PaperOperationEvidenceEvaluator, SQLitePaperOperationEvidenceStore


CANONICAL_BENCHMARK_LABEL = "80% VTI / 20% SGOV"
CANONICAL_BENCHMARK_DETAIL = (
    "Frozen paper-experiment benchmark: 80% VTI and 20% SGOV, valued from the "
    "same point-in-time quote authority with recorded implementation costs."
)


@dataclass(frozen=True, slots=True)
class BenchmarkPortfolioRow:
    label: str
    compounded_return: float
    excess_vs_system: float
    detail: str
    kind: str


@dataclass(frozen=True, slots=True)
class BenchmarkPortfolioComparison:
    state: str
    detail: str
    period_start: datetime | None
    period_end: datetime | None
    observation_count: int
    rows: tuple[BenchmarkPortfolioRow, ...]
    system_maximum_drawdown: float | None
    evidence_status: str | None
    evaluated_at: datetime | None
    evaluation_only: bool = True
    investment_authority_changed: bool = False
    real_money_authorized: bool = False


def unavailable_comparison(detail: str = "Benchmark evidence is not available yet.") -> BenchmarkPortfolioComparison:
    return BenchmarkPortfolioComparison(
        state="unavailable",
        detail=detail,
        period_start=None,
        period_end=None,
        observation_count=0,
        rows=(),
        system_maximum_drawdown=None,
        evidence_status=None,
        evaluated_at=None,
    )


def load_benchmark_portfolio_comparison(
    database: str | Path | None = None,
) -> BenchmarkPortfolioComparison:
    """Synchronously load a truthful same-window comparison from immutable evidence."""
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    path = Path(database).expanduser() if database is not None else data_dir / "paper_operation_evidence.db"
    if not path.exists():
        return unavailable_comparison(
            "No paper-operation benchmark observations have been recorded yet. "
            "The comparison will appear after point-in-time portfolio and reference returns exist."
        )

    store = SQLitePaperOperationEvidenceStore(path, initialize=False)
    try:
        store.verify_integrity()
        report = store.latest_report()
        if report is None:
            observations = tuple(reversed(store.observations()))
            if not observations:
                return unavailable_comparison(
                    "The paper-operation evidence store exists but contains no benchmark observations yet."
                )
            report = PaperOperationEvidenceEvaluator().evaluate(
                observations,
                evaluated_at=datetime.now(timezone.utc),
            )
    except Exception as error:
        return unavailable_comparison(
            "Benchmark evidence could not be read safely; the comparison is withheld "
            f"({type(error).__name__})."
        )

    system_return = float(report.compounded_portfolio_return)
    references = (
        (
            CANONICAL_BENCHMARK_LABEL,
            float(report.compounded_benchmark_return),
            CANONICAL_BENCHMARK_DETAIL,
            "canonical_benchmark",
        ),
        (
            "Passive reference portfolio",
            float(report.compounded_passive_return),
            "The passive reference frozen in the recorded paper-operation evidence.",
            "passive_reference",
        ),
        (
            "Cash reference",
            float(report.compounded_cash_return),
            "The cash return recorded over the same point-in-time observation window.",
            "cash_reference",
        ),
    )
    rows = (
        BenchmarkPortfolioRow(
            label="System paper portfolio",
            compounded_return=system_return,
            excess_vs_system=0.0,
            detail="The canonical governed paper portfolio after recorded implementation costs.",
            kind="system",
        ),
        *tuple(
            BenchmarkPortfolioRow(
                label=label,
                compounded_return=value,
                excess_vs_system=round(value - system_return, 12),
                detail=detail,
                kind=kind,
            )
            for label, value, detail, kind in references
        ),
    )
    return BenchmarkPortfolioComparison(
        state="available",
        detail=(
            "All returns use the same recorded paper-operation window. References are "
            "evaluation yardsticks only and never become a second investment objective."
        ),
        period_start=report.period_start,
        period_end=report.period_end,
        observation_count=int(report.observation_count),
        rows=rows,
        system_maximum_drawdown=float(report.maximum_drawdown),
        evidence_status=report.status.value,
        evaluated_at=report.evaluated_at,
    )


_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: BenchmarkPortfolioComparison | None = None
_CACHE_UPDATED_AT = 0.0
_CACHE_REFRESHING = False
_CACHE_TTL_SECONDS = 30.0


def _refresh_default_comparison() -> None:
    global _CACHE_VALUE, _CACHE_UPDATED_AT, _CACHE_REFRESHING
    try:
        value = load_benchmark_portfolio_comparison()
        with _CACHE_LOCK:
            _CACHE_VALUE = value
            _CACHE_UPDATED_AT = time.monotonic()
    finally:
        with _CACHE_LOCK:
            _CACHE_REFRESHING = False


def load_benchmark_portfolio_comparison_nonblocking() -> BenchmarkPortfolioComparison:
    """Return cached evidence immediately while SQLite verification refreshes off-thread."""
    global _CACHE_REFRESHING
    now = time.monotonic()
    with _CACHE_LOCK:
        if _CACHE_VALUE is not None and now - _CACHE_UPDATED_AT <= _CACHE_TTL_SECONDS:
            return _CACHE_VALUE
        stale = _CACHE_VALUE
        if not _CACHE_REFRESHING:
            _CACHE_REFRESHING = True
            thread = threading.Thread(
                target=_refresh_default_comparison,
                name="render-benchmark-comparison-refresh",
                daemon=True,
            )
            thread.start()
        if stale is not None:
            return stale
    return unavailable_comparison(
        "Benchmark comparison evidence is refreshing in the background. "
        "No reference return is shown until the governed evidence read completes."
    )


def reset_benchmark_portfolio_comparison_cache() -> None:
    """Reset display cache for deterministic tests."""
    global _CACHE_VALUE, _CACHE_UPDATED_AT, _CACHE_REFRESHING
    with _CACHE_LOCK:
        _CACHE_VALUE = None
        _CACHE_UPDATED_AT = 0.0
        _CACHE_REFRESHING = False


__all__ = [
    "BenchmarkPortfolioComparison",
    "BenchmarkPortfolioRow",
    "CANONICAL_BENCHMARK_DETAIL",
    "CANONICAL_BENCHMARK_LABEL",
    "load_benchmark_portfolio_comparison",
    "load_benchmark_portfolio_comparison_nonblocking",
    "reset_benchmark_portfolio_comparison_cache",
    "unavailable_comparison",
]
