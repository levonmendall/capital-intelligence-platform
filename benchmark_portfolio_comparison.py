"""Read-only market benchmark comparison for the canonical paper portfolio.

The comparison consumes existing point-in-time paper-operation evidence for the
system return and read-only adjusted Alpaca/IEX daily bars for familiar market
benchmark ETFs. It is measurement only: it cannot nominate an asset, alter a
threshold, affect CIO qualification, size a position, construct a portfolio, or
authorize execution.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from evaluation import PaperOperationEvidenceEvaluator, SQLitePaperOperationEvidenceStore
from providers.alpaca_paper import AlpacaPaperClient, AlpacaPaperSettings


MARKET_BENCHMARKS = (
    ("SPY", "S&P 500", "U.S. large-cap equity benchmark."),
    ("QQQ", "Nasdaq-100", "Growth- and technology-heavy U.S. large-cap equity benchmark."),
    ("VTI", "Total U.S. stock market", "Broad U.S. equity benchmark."),
    ("VT", "Total world equities", "Global developed and emerging-market equity benchmark."),
    ("AGG", "U.S. aggregate bonds", "Broad investment-grade U.S. fixed-income benchmark."),
    ("SGOV", "0–3 month U.S. Treasuries", "Cash-like short U.S. Treasury benchmark."),
)
MARKET_BENCHMARK_SYMBOLS = tuple(item[0] for item in MARKET_BENCHMARKS)
MARKET_DATA_SOURCE = "Alpaca/IEX adjusted daily bars"


@dataclass(frozen=True, slots=True)
class BenchmarkPortfolioRow:
    symbol: str | None
    label: str
    compounded_return: float | None
    system_excess_return: float | None
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
    market_data_source: str | None = None
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


def _bar_close(bar: Mapping[str, Any]) -> float | None:
    raw = bar.get("c", bar.get("close"))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _benchmark_return(bars: Sequence[Mapping[str, Any]]) -> float | None:
    closes = tuple(value for item in bars if (value := _bar_close(item)) is not None)
    if len(closes) < 2:
        return None
    return round(closes[-1] / closes[0] - 1.0, 12)


def _load_market_returns(
    *,
    period_start: datetime,
    period_end: datetime,
    market_client: AlpacaPaperClient | None = None,
) -> dict[str, float | None]:
    """Read adjusted ETF returns over the evidence window without authority."""
    client = market_client or AlpacaPaperClient(AlpacaPaperSettings.from_env())
    bars = client.historical_bars(
        MARKET_BENCHMARK_SYMBOLS,
        start=period_start,
        end=period_end + timedelta(days=1),
        timeframe="1Day",
    )
    return {
        symbol: _benchmark_return(tuple(bars.get(symbol, ())))
        for symbol in MARKET_BENCHMARK_SYMBOLS
    }


def load_benchmark_portfolio_comparison(
    database: str | Path | None = None,
    *,
    market_client: AlpacaPaperClient | None = None,
    _background: bool = False,
) -> BenchmarkPortfolioComparison:
    """Load a truthful same-window system-versus-market comparison.

    The no-argument presentation call is nonblocking. Explicit database/client
    calls remain synchronous for deterministic evaluation and tests.
    """
    if database is None and market_client is None and not _background:
        return load_benchmark_portfolio_comparison_nonblocking()

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    path = Path(database).expanduser() if database is not None else data_dir / "paper_operation_evidence.db"
    if not path.exists():
        return unavailable_comparison(
            "No paper-operation observations have been recorded yet. Market benchmark "
            "comparison begins only after a point-in-time system return exists."
        )

    store = SQLitePaperOperationEvidenceStore(path, initialize=False)
    try:
        store.verify_integrity()
        report = store.latest_report()
        if report is None:
            observations = tuple(reversed(store.observations()))
            if not observations:
                return unavailable_comparison(
                    "The paper-operation evidence store exists but contains no return observations yet."
                )
            report = PaperOperationEvidenceEvaluator().evaluate(
                observations,
                evaluated_at=datetime.now(timezone.utc),
            )
    except Exception as error:
        return unavailable_comparison(
            "Portfolio evidence could not be read safely; benchmark comparison is withheld "
            f"({type(error).__name__})."
        )

    if report.period_start is None or report.period_end is None:
        return unavailable_comparison("The recorded system return does not yet have a complete evaluation window.")

    system_return = float(report.compounded_portfolio_return)
    market_error: str | None = None
    try:
        market_returns = _load_market_returns(
            period_start=report.period_start,
            period_end=report.period_end,
            market_client=market_client,
        )
    except Exception as error:
        market_returns = {symbol: None for symbol in MARKET_BENCHMARK_SYMBOLS}
        market_error = type(error).__name__

    rows: list[BenchmarkPortfolioRow] = [
        BenchmarkPortfolioRow(
            symbol=None,
            label="System paper portfolio",
            compounded_return=system_return,
            system_excess_return=0.0,
            detail="Canonical governed paper portfolio after recorded implementation costs.",
            kind="system",
        )
    ]
    available_market_count = 0
    for symbol, label, detail in MARKET_BENCHMARKS:
        value = market_returns.get(symbol)
        if value is not None:
            available_market_count += 1
        rows.append(
            BenchmarkPortfolioRow(
                symbol=symbol,
                label=label,
                compounded_return=value,
                system_excess_return=None if value is None else round(system_return - value, 12),
                detail=detail,
                kind="market_benchmark",
            )
        )

    if available_market_count == len(MARKET_BENCHMARKS):
        state = "available"
        detail = (
            "System and market benchmarks use the same recorded evaluation window. ETF returns "
            "come from adjusted daily market bars. Benchmarks are evaluation yardsticks only."
        )
    elif available_market_count:
        state = "partial"
        detail = (
            f"{available_market_count} of {len(MARKET_BENCHMARKS)} market benchmarks have complete "
            "same-window data. Missing benchmark returns are withheld rather than estimated."
        )
    else:
        state = "partial"
        suffix = "" if market_error is None else f" ({market_error})"
        detail = (
            "System performance is available, but market benchmark data is currently unavailable" + suffix + ". "
            "No benchmark return is estimated or substituted."
        )

    return BenchmarkPortfolioComparison(
        state=state,
        detail=detail,
        period_start=report.period_start,
        period_end=report.period_end,
        observation_count=int(report.observation_count),
        rows=tuple(rows),
        system_maximum_drawdown=float(report.maximum_drawdown),
        evidence_status=report.status.value,
        evaluated_at=report.evaluated_at,
        market_data_source=MARKET_DATA_SOURCE,
    )


_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: BenchmarkPortfolioComparison | None = None
_CACHE_UPDATED_AT = 0.0
_CACHE_REFRESHING = False
_CACHE_TTL_SECONDS = 30.0


def _refresh_default_comparison() -> None:
    global _CACHE_VALUE, _CACHE_UPDATED_AT, _CACHE_REFRESHING
    try:
        value = load_benchmark_portfolio_comparison(_background=True)
        with _CACHE_LOCK:
            _CACHE_VALUE = value
            _CACHE_UPDATED_AT = time.monotonic()
    finally:
        with _CACHE_LOCK:
            _CACHE_REFRESHING = False


def load_benchmark_portfolio_comparison_nonblocking() -> BenchmarkPortfolioComparison:
    """Return cached evidence immediately while market/evidence reads refresh off-thread."""
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
                name="render-market-benchmark-comparison-refresh",
                daemon=True,
            )
            thread.start()
        if stale is not None:
            return stale
    return unavailable_comparison(
        "Market benchmark comparison is refreshing in the background. No reference return "
        "is shown until the governed portfolio evidence and market data reads complete."
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
    "MARKET_BENCHMARKS",
    "MARKET_BENCHMARK_SYMBOLS",
    "MARKET_DATA_SOURCE",
    "load_benchmark_portfolio_comparison",
    "load_benchmark_portfolio_comparison_nonblocking",
    "reset_benchmark_portfolio_comparison_cache",
    "unavailable_comparison",
]
