"""Observe canonical deep-market work units without changing provider behavior.

Spawned certification lanes can outlive the ordinary stall budget while genuine work is
still completing. This module scopes a lightweight Python profiler to one spawned lane and
counts only credential-safe completion events from the existing canonical per-record
feature builder and governed fallback routers. A single reporter thread publishes those
counts through the existing child progress transport.

No provider call is wrapped or replaced. No market membership, evidence rule, ordering,
threshold, CIO authority, construction, execution, or paper-only control is changed.
"""

from __future__ import annotations

import sys
import threading
from types import FrameType
from typing import Callable, Mapping, Sequence

from operations.certification_work_progress import record_certification_work_progress


# True means the event is also a completed per-record primary evidence evaluation. Other
# events are bounded provider/router work units that advance the stall clock without
# claiming another catalog record has reached terminal evidence disposition.
_TARGET_RETURNS = {
    ("operations.comprehensive_market_discovery_legacy", "build_record_features"): True,
    ("providers.redundant_market_history", "fetch"): False,
    ("providers.alpaca_crypto_history", "daily_history_many"): False,
    ("providers.redundant_options", "latest_daily_bars"): False,
    ("providers.redundant_options", "select_contracts"): False,
    ("providers.tradier_market_data", "active_option_chain"): False,
    ("operations._redundant_market_probe_core", "_corroborate_options"): False,
}
_REPORT_INTERVAL_SECONDS = 0.25
_REPORTER_JOIN_SECONDS = 2.0


class _CompletedWorkCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._work_units = 0
        self._record_units = 0

    def increment(self, *, record_completed: bool) -> None:
        with self._lock:
            self._work_units += 1
            if record_completed:
                self._record_units += 1

    def value(self) -> tuple[int, int]:
        with self._lock:
            return self._work_units, self._record_units


def _work_profile(counter: _CompletedWorkCounter):
    def profile(frame: FrameType, event: str, _arg: object):
        if event != "return":
            return profile
        module = str(frame.f_globals.get("__name__") or "")
        record_completed = _TARGET_RETURNS.get((module, frame.f_code.co_name))
        if record_completed is not None:
            counter.increment(record_completed=record_completed)
        return profile

    return profile


def run_with_canonical_work_progress(
    delegate: Callable[[Sequence[object], object, object], Mapping[str, object]],
    *,
    records: Sequence[object],
    timestamp: object,
    policy: object,
    asset_class: str,
) -> Mapping[str, object]:
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

    emitted_work_units = [0]
    publication_lock = threading.Lock()

    def publish_if_advanced() -> None:
        work_units, record_units = counter.value()
        with publication_lock:
            if work_units <= emitted_work_units[0]:
                return
            delta = work_units - emitted_work_units[0]
            emitted_work_units[0] = work_units
            record_certification_work_progress(
                asset_class,
                processed_records=(
                    min(record_units, total_records) if total_records else record_units
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
    # all transport publication is serialized by the reporter thread.
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
