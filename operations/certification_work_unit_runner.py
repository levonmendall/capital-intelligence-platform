"""Observe canonical deep-market work units without changing provider behavior.

Spawned certification lanes can outlive the ordinary stall budget while genuine work is
still completing. This module scopes a lightweight Python profiler to one spawned lane and
counts only credential-safe completion events from the existing canonical per-record
feature builder and governed fallback routers. A single reporter thread publishes those
counts through the existing diagnostic progress transport.

No provider call is wrapped or replaced. No market membership, evidence rule, ordering,
threshold, CIO authority, construction, execution, or paper-only control is changed.
"""

from __future__ import annotations

import sys
import threading
import time
from types import FrameType
from typing import Any, Callable, Mapping, Sequence

from operations.certification_work_progress import record_certification_work_progress


_TARGET_RETURNS = frozenset(
    {
        ("operations.comprehensive_market_discovery_legacy", "build_record_features"),
        ("providers.redundant_market_history", "fetch"),
        ("providers.alpaca_crypto_history", "daily_history_many"),
        ("providers.redundant_options", "latest_daily_bars"),
        ("providers.redundant_options", "select_contracts"),
        ("providers.tradier_market_data", "active_option_chain"),
        ("operations._redundant_market_probe_core", "_corroborate_options"),
    }
)
_REPORT_INTERVAL_SECONDS = 0.25
_REPORTER_JOIN_SECONDS = 2.0


class _CompletedWorkCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._completed = 0

    def increment(self) -> None:
        with self._lock:
            self._completed += 1

    def value(self) -> int:
        with self._lock:
            return self._completed


def _work_profile(counter: _CompletedWorkCounter):
    def profile(frame: FrameType, event: str, _arg: object):
        if event != "return":
            return profile
        module = str(frame.f_globals.get("__name__") or "")
        if (module, frame.f_code.co_name) in _TARGET_RETURNS:
            counter.increment()
        return profile

    return profile


def run_with_canonical_work_progress(
    delegate: Callable[[Sequence[object], object, object], Mapping[str, object]],
    *,
    records: Sequence[object],
    timestamp: object,
    policy: object,
    asset_class: str,
):
    """Run one unchanged lane probe while reporting completed canonical work units."""

    governed_records = tuple(records)
    total_records = len(governed_records)
    counter = _CompletedWorkCounter()
    profile = _work_profile(counter)
    stop = threading.Event()
    previous_main_profile = sys.getprofile()
    get_thread_profile = getattr(threading, "getprofile", None)
    previous_thread_profile = (
        get_thread_profile() if callable(get_thread_profile) else None
    )

    emitted = [0]

    def publish_if_advanced() -> None:
        completed = counter.value()
        if completed <= emitted[0]:
            return
        delta = completed - emitted[0]
        emitted[0] = completed
        record_certification_work_progress(
            asset_class,
            processed_records=(
                min(completed, total_records) if total_records else completed
            ),
            total_records=total_records,
            chunk_records=delta,
        )

    def reporter() -> None:
        while not stop.wait(_REPORT_INTERVAL_SECONDS):
            publish_if_advanced()
        publish_if_advanced()

    # Install before the probe creates its ThreadPoolExecutor so worker threads inherit
    # the same completion observer. The callback only increments an in-memory counter;
    # all durable publication is serialized by the reporter thread.
    sys.setprofile(profile)
    threading.setprofile(profile)
    report_thread = threading.Thread(
        target=reporter,
        name="certification-work-progress",
        daemon=True,
    )
    report_thread.start()
    try:
        return delegate(governed_records, timestamp, policy)
    finally:
        sys.setprofile(previous_main_profile)
        threading.setprofile(previous_thread_profile)
        stop.set()
        report_thread.join(timeout=_REPORTER_JOIN_SECONDS)
        publish_if_advanced()


__all__ = ["run_with_canonical_work_progress"]
