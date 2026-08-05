"""Memory-bounded concurrent evidence collection for broad paper-candidate analysis.

The cycle-local spool remains append-only and disk-backed. This runtime collector overlaps
issuer-level SEC requests while spacing issuer starts so simultaneous Render processes stay
below the SEC fair-access request ceiling. Only a bounded number of provider results may
exist in memory at once, and all SQLite writes remain on the calling thread. The collector
has no candidate, CIO, construction, execution, or real-money authority.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Callable

from operations.paper_evidence_spool import (
    SQLitePaperEvidenceSpool,
    close_spooled_paper_evidence,
)

_DEFAULT_LISTED_BATCH_SIZE = 10
_DEFAULT_SEC_WORKERS = 2
_MAXIMUM_SEC_WORKERS = 4
_DEFAULT_SEC_ISSUER_START_INTERVAL_SECONDS = 0.45
_PROGRESS_INTERVAL = 25


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _batches(values: Sequence[object], size: int):
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("batch size must be a positive integer")
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def _log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-paper-evidence-collector",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidate_authority": False,
                "sizing_authority": False,
                "execution_authority": False,
                "real_money_authorized": False,
                "secret_values_disclosed": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


class _IssuerStartGate:
    """Space issuer starts across worker threads without holding the lock while sleeping."""

    def __init__(self, interval_seconds: float) -> None:
        interval = float(interval_seconds)
        if interval < 0:
            raise ValueError("SEC issuer start interval cannot be negative")
        self._interval = interval
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait(self) -> None:
        if self._interval == 0:
            return
        with self._lock:
            now = time.monotonic()
            scheduled = max(now, self._next_start)
            self._next_start = scheduled + self._interval
        delay = scheduled - now
        if delay > 0:
            time.sleep(delay)


def _fetch_company_facts(
    instrument,
    *,
    as_of: datetime,
    gate: _IssuerStartGate,
    sec_provider_factory: Callable[[], object],
    filing_query_type: type,
):
    gate.wait()
    provider = sec_provider_factory()
    facts = provider.fetch_company_facts(
        filing_query_type(
            cik=instrument.issuer_cik,
            as_of=as_of,
            forms=(
                "10-K",
                "10-K/A",
                "20-F",
                "20-F/A",
                "40-F",
                "40-F/A",
            ),
            limit=10_000,
        )
    )
    return instrument.symbol, facts


def _collect_company_facts(
    *,
    spool: SQLitePaperEvidenceSpool,
    instruments: tuple[object, ...],
    as_of: datetime,
    sec_provider_factory: Callable[[], object],
    filing_query_type: type,
    workers: int,
    issuer_start_interval_seconds: float,
) -> None:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("SEC fact workers must be a positive integer")
    if workers > _MAXIMUM_SEC_WORKERS:
        raise ValueError(
            f"SEC fact workers cannot exceed {_MAXIMUM_SEC_WORKERS}"
        )

    eligible = tuple(
        instrument for instrument in instruments if instrument.issuer_cik is not None
    )
    total = len(eligible)
    gate = _IssuerStartGate(issuer_start_interval_seconds)
    executor = ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="sec-company-facts",
    )
    pending: dict[Future[tuple[str, object]], object] = {}
    instrument_iterator = iter(eligible)
    maximum_in_flight = 0

    def submit_next() -> bool:
        nonlocal maximum_in_flight
        try:
            instrument = next(instrument_iterator)
        except StopIteration:
            return False
        future = executor.submit(
            _fetch_company_facts,
            instrument,
            as_of=as_of,
            gate=gate,
            sec_provider_factory=sec_provider_factory,
            filing_query_type=filing_query_type,
        )
        pending[future] = instrument
        maximum_in_flight = max(maximum_in_flight, len(pending))
        return True

    try:
        for _ in range(min(workers, total)):
            submit_next()
        _log(
            "paper_evidence_company_facts_started",
            issuer_count=total,
            worker_count=workers,
            maximum_in_flight_limit=workers,
            issuer_start_interval_seconds=issuer_start_interval_seconds,
        )
        completed = 0
        while pending:
            completed_futures, _ = wait(
                tuple(pending),
                return_when=FIRST_COMPLETED,
            )
            for future in completed_futures:
                pending.pop(future, None)
                symbol, facts = future.result()
                try:
                    spool.append(
                        "company_facts",
                        symbol,
                        facts,
                        recorded_at=as_of,
                    )
                finally:
                    del facts
                completed += 1
                submit_next()
                if completed % _PROGRESS_INTERVAL == 0 or completed == total:
                    _log(
                        "paper_evidence_company_facts_progress",
                        completed_issuer_count=completed,
                        issuer_count=total,
                        in_flight_count=len(pending),
                        maximum_in_flight_count=maximum_in_flight,
                    )
        _log(
            "paper_evidence_company_facts_completed",
            issuer_count=total,
            maximum_in_flight_count=maximum_in_flight,
        )
    except Exception:
        for future in pending:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def collect_spooled_paper_evidence(
    universe,
    decision_as_of: datetime,
    *,
    create_alpaca_client: Callable[[], object],
    sec_provider_factory: Callable[[], object],
    fred_provider_factory: Callable[[], object],
    direct_market_client_type: type,
    direct_market_universe_type: type,
    filing_query_type: type,
    candidate_asset_class: type,
    instrument_evaluation_scheduled: Callable[[object, datetime], bool],
    history_days: int,
    listed_batch_size: int = _DEFAULT_LISTED_BATCH_SIZE,
    sec_workers: int = _DEFAULT_SEC_WORKERS,
    sec_issuer_start_interval_seconds: float = (
        _DEFAULT_SEC_ISSUER_START_INTERVAL_SECONDS
    ),
) -> Mapping[str, object]:
    """Collect full evidence scope through bounded provider batches and lazy storage."""

    as_of = _aware(decision_as_of, field_name="decision_as_of")
    scheduled_instruments = tuple(
        item
        for item in universe.instruments
        if instrument_evaluation_scheduled(item, as_of)
    )
    scheduled_closed_symbols = tuple(
        item.symbol for item in universe.instruments if item not in scheduled_instruments
    )
    listed_instruments = tuple(
        item for item in scheduled_instruments if not item.uses_direct_market_provider
    )
    direct_instruments = tuple(
        item for item in scheduled_instruments if item.uses_direct_market_provider
    )
    stock_instruments = tuple(
        item
        for item in scheduled_instruments
        if item.execution_asset_class is candidate_asset_class.US_EQUITY
        and item.instrument_type == "common_stock"
    )
    spool = SQLitePaperEvidenceSpool.create(
        universe_identifier=universe.identifier,
        as_of=as_of,
    )
    client = None
    direct_market_errors: dict[str, str] = {}
    _log(
        "paper_evidence_collection_started",
        universe_identifier=universe.identifier,
        scheduled_instrument_count=len(scheduled_instruments),
        listed_instrument_count=len(listed_instruments),
        direct_instrument_count=len(direct_instruments),
        company_instrument_count=len(stock_instruments),
    )
    try:
        if listed_instruments:
            client = create_alpaca_client()
            batches = tuple(_batches(listed_instruments, listed_batch_size))
            for batch_index, raw_batch in enumerate(batches, start=1):
                batch = tuple(raw_batch)
                symbols = tuple(item.symbol for item in batch)
                batch_bars = client.historical_bars(
                    symbols,
                    start=as_of - timedelta(days=history_days),
                    end=as_of,
                    timeframe="1Day",
                )
                batch_quotes = client.latest_quotes(symbols)
                for symbol in symbols:
                    if symbol in batch_bars:
                        spool.append(
                            "bars",
                            symbol,
                            batch_bars[symbol],
                            recorded_at=as_of,
                        )
                    if symbol in batch_quotes:
                        spool.append(
                            "quotes",
                            symbol,
                            batch_quotes[symbol],
                            recorded_at=as_of,
                        )
                del batch_bars
                del batch_quotes
                if batch_index % 10 == 0 or batch_index == len(batches):
                    _log(
                        "paper_evidence_listed_progress",
                        completed_batch_count=batch_index,
                        batch_count=len(batches),
                        completed_instrument_count=min(
                            batch_index * listed_batch_size,
                            len(listed_instruments),
                        ),
                        listed_instrument_count=len(listed_instruments),
                    )

        if direct_instruments:
            direct_client = direct_market_client_type(
                direct_market_universe_type(
                    identifier=f"dynamic-direct-evidence:{universe.identifier}",
                    provider_identifier="comprehensive-direct-market-evidence.v1",
                    instruments=direct_instruments,
                    limitations=universe.limitations,
                )
            )
            for index, instrument in enumerate(direct_instruments, start=1):
                symbol = instrument.symbol
                try:
                    symbol_bars = direct_client.historical_bars(
                        (symbol,),
                        start=as_of - timedelta(days=history_days),
                        end=as_of,
                        timeframe="1Day",
                    )
                    symbol_quotes = direct_client.latest_quotes((symbol,))
                except (OSError, TypeError, ValueError, RuntimeError) as error:
                    direct_market_errors[symbol] = (
                        f"{type(error).__name__}: {str(error)[:300]}"
                    )
                    continue
                if symbol in symbol_bars:
                    spool.append(
                        "bars",
                        symbol,
                        symbol_bars[symbol],
                        recorded_at=as_of,
                    )
                if symbol in symbol_quotes:
                    spool.append(
                        "quotes",
                        symbol,
                        symbol_quotes[symbol],
                        recorded_at=as_of,
                    )
                del symbol_bars
                del symbol_quotes
                if index % _PROGRESS_INTERVAL == 0 or index == len(direct_instruments):
                    _log(
                        "paper_evidence_direct_progress",
                        completed_instrument_count=index,
                        direct_instrument_count=len(direct_instruments),
                        failed_instrument_count=len(direct_market_errors),
                    )

        fred = fred_provider_factory()
        macro = {
            series: fred.get_latest_value(series)
            for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF")
        }
        if stock_instruments:
            _collect_company_facts(
                spool=spool,
                instruments=stock_instruments,
                as_of=as_of,
                sec_provider_factory=sec_provider_factory,
                filing_query_type=filing_query_type,
                workers=sec_workers,
                issuer_start_interval_seconds=sec_issuer_start_interval_seconds,
            )

        provider_clock = (
            client.clock()
            if client is not None
            else {
                "timestamp": as_of.isoformat(),
                "is_open": False,
                "source": "governed_collection_clock",
            }
        )
    except Exception:
        spool.close(remove=True)
        _log("paper_evidence_collection_failed")
        raise

    _log(
        "paper_evidence_collection_completed",
        bar_count=spool.count("bars"),
        quote_count=spool.count("quotes"),
        company_fact_symbol_count=spool.count("company_facts"),
        direct_market_error_count=len(direct_market_errors),
    )
    return {
        "bars": spool.mapping("bars"),
        "quotes": spool.mapping("quotes"),
        "macro": macro,
        "company_facts": spool.mapping("company_facts", tuple_result=True),
        "provider_clock": provider_clock,
        "_direct_market_errors": direct_market_errors,
        "_scheduled_closed_symbols": scheduled_closed_symbols,
        "_evidence_spool": spool,
        "_evidence_spool_policy": spool.policy_version,
    }


__all__ = [
    "close_spooled_paper_evidence",
    "collect_spooled_paper_evidence",
]
