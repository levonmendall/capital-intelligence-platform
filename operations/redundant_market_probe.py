"""Bounded-concurrent production market-evidence probe.

The previous implementation is preserved in ``_redundant_market_probe_core``.  This
public wrapper keeps provider routing and evidence contracts unchanged while replacing
the serial missing-record failover loop with bounded concurrent I/O.  Comprehensive
market scope is not reduced: every decision-eligible record is still attempted and must
receive the same selected-or-excluded terminal accounting upstream.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local
from typing import Callable, Mapping, Sequence

import requests

from operations import _redundant_market_probe_core as _core
from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress

_DEFAULT_DEEP_MARKET_IO_WORKERS = 8
_MAX_DEEP_MARKET_IO_WORKERS = 16
_DEEP_EVIDENCE_PROGRESS_INTERVAL = 16
_PENDING_FUTURES_PER_WORKER = 4

# Preserve the former module's public surface for callers that imported provider
# classes/helpers from here instead of the canonical provider modules.
for _name in dir(_core):
    if not _name.startswith("_") and _name != "default_redundant_market_probe":
        globals()[_name] = getattr(_core, _name)


def __getattr__(name: str):
    return getattr(_core, name)


def _resolved_worker_count(record_count: int, override: int | None = None) -> int:
    """Return a bounded I/O worker count without allowing unbounded provider fan-out."""

    requested = override
    if requested is None:
        raw = os.getenv("CAPITAL_INTELLIGENCE_DEEP_MARKET_IO_WORKERS", "").strip()
        if raw:
            try:
                requested = int(raw)
            except ValueError:
                requested = None
    if requested is None:
        requested = _DEFAULT_DEEP_MARKET_IO_WORKERS
    if isinstance(requested, bool) or not isinstance(requested, int):
        raise TypeError("maximum_workers must be an integer or None")
    if requested < 1:
        raise ValueError("maximum_workers must be positive")
    return min(_MAX_DEEP_MARKET_IO_WORKERS, requested, max(1, record_count))


def _progress_lane(records: Sequence[object]) -> str | None:
    asset_classes = {
        getattr(getattr(record, "asset_class", None), "value", "")
        for record in records
    }
    asset_classes.discard("")
    return next(iter(asset_classes)) if len(asset_classes) == 1 else None


def _record_deep_progress(
    lane: str | None,
    *,
    decision_eligible_records: int,
    processed_records: int,
    evidence_complete_records: int,
    callback: Callable[..., object],
) -> None:
    if lane is None:
        return
    callback(
        f"deep_market_evidence:{lane}",
        metrics={
            "decision_eligible_records": decision_eligible_records,
            "processed_records": processed_records,
            "total_records": decision_eligible_records,
            "evidence_complete_records": evidence_complete_records,
        },
    )


def _fetch_missing_concurrently(
    missing: Sequence[object],
    *,
    timestamp,
    policy,
    http_get,
    eodhd,
    tradier,
    massive,
    twelve,
    coinbase,
    kraken,
    alpaca_crypto_rows: Mapping[str, Sequence[object]],
    already_processed: int,
    already_evidence_complete: int,
    decision_eligible_records: int,
    maximum_workers: int | None = None,
    progress_callback: Callable[..., object] = record_manual_cio_diagnostic_progress,
):
    """Fetch unresolved evidence with bounded pending work and deterministic output.

    A thread-local router preserves each worker's cycle-local permanent-failure cache
    without sharing mutable router state.  The redundancy audit ledger itself is
    explicitly thread-safe, so provider attempt/use/failover observations remain safe.
    """

    ordered = tuple(missing)
    if not ordered:
        return {}

    worker_count = _resolved_worker_count(len(ordered), maximum_workers)
    pending_limit = max(worker_count, worker_count * _PENDING_FUTURES_PER_WORKER)
    ledger = _core.current_redundancy_ledger()
    thread_state = local()
    lane = _progress_lane(ordered)

    def fetch_one(record):
        router = getattr(thread_state, "router", None)
        if router is None:
            router = _core.RedundantMarketHistoryRouter(audit=ledger)
            thread_state.router = router
        candidates = _core._candidate_set(
            record,
            as_of=timestamp,
            policy=policy,
            http_get=http_get,
            eodhd_provider=eodhd,
            tradier=tradier,
            massive=massive,
            twelve=twelve,
            coinbase=coinbase,
            kraken=kraken,
            alpaca_crypto_rows=alpaca_crypto_rows,
        )
        if ledger is not None:
            for candidate in candidates:
                ledger.declare(
                    candidate.key,
                    configured=candidate.configured,
                    authenticated=candidate.authenticated,
                    routed=True,
                    certified_for_evidence_role=candidate.certified_for_evidence_role,
                )
        if not candidates:
            return record.symbol, None
        try:
            routed = router.fetch(
                candidates,
                as_of=timestamp,
                minimum_rows=policy.minimum_history_bars,
            )
        except _core.RedundantMarketHistoryError:
            return record.symbol, None
        return (
            record.symbol,
            _core._feature_from_rows(
                record,
                routed.rows,
                routed.evidence_identifiers,
            ),
        )

    fetched: dict[str, object] = {}
    completed = 0
    successful = 0
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="redundant-market-evidence",
    ) as executor:
        for start in range(0, len(ordered), pending_limit):
            batch = ordered[start : start + pending_limit]
            futures = {executor.submit(fetch_one, record): record for record in batch}
            for future in as_completed(futures):
                symbol, feature = future.result()
                completed += 1
                if feature is not None:
                    fetched[symbol] = feature
                    successful += 1
                total_processed = already_processed + completed
                if (
                    completed % _DEEP_EVIDENCE_PROGRESS_INTERVAL == 0
                    or completed == len(ordered)
                ):
                    _record_deep_progress(
                        lane,
                        decision_eligible_records=decision_eligible_records,
                        processed_records=total_processed,
                        evidence_complete_records=(
                            already_evidence_complete + successful
                        ),
                        callback=progress_callback,
                    )

    # Preserve input order despite completion-order concurrency.  This keeps downstream
    # fingerprints and terminal accounting deterministic for identical provider data.
    return {
        record.symbol: fetched[record.symbol]
        for record in ordered
        if record.symbol in fetched
    }


def default_redundant_market_probe(
    records,
    as_of,
    policy,
    *,
    http_get=requests.get,
    maximum_workers: int | None = None,
):
    timestamp = _core._legacy._aware(as_of, field_name="as_of")
    if _core.current_redundancy_ledger() is None:
        _core.begin_redundancy_cycle(
            f"cio-market-evidence:{timestamp.isoformat()}",
            timestamp,
        )

    records = tuple(records)
    primary_records = tuple(_core._primary_probe_record(record) for record in records)
    result = dict(
        _core._legacy.default_market_probe(
            primary_records,
            timestamp,
            policy,
            http_get=http_get,
        )
    )
    _core._mark_existing_result_usage(primary_records, result)
    missing = tuple(
        record
        for record in records
        if record.symbol not in result
        and record.asset_class is not _core.CandidateAssetClass.OPTION
    )

    if missing:
        eodhd = _core._legacy.build_eodhd_provider()
        tradier = _core.TradierMarketDataProvider()
        massive = _core.MassiveMultiAssetProvider()
        twelve = _core.TwelveDataHistoryProvider()
        coinbase = _core.CoinbaseHistoryProvider()
        kraken = _core.KrakenHistoryProvider()
        alpaca_crypto_rows = _core._prefetch_alpaca_crypto(
            missing,
            as_of=timestamp,
            policy=policy,
            provider=_core.AlpacaCryptoHistoryProvider(http_get=http_get),
        )
        fetched = _fetch_missing_concurrently(
            missing,
            timestamp=timestamp,
            policy=policy,
            http_get=http_get,
            eodhd=eodhd,
            tradier=tradier,
            massive=massive,
            twelve=twelve,
            coinbase=coinbase,
            kraken=kraken,
            alpaca_crypto_rows=alpaca_crypto_rows,
            already_processed=len(records) - len(missing),
            already_evidence_complete=len(result),
            decision_eligible_records=len(records),
            maximum_workers=maximum_workers,
        )
        result.update(fetched)

    return _core._corroborate_options(
        records,
        result,
        as_of=timestamp,
        tradier=_core.TradierMarketDataProvider(),
    )
