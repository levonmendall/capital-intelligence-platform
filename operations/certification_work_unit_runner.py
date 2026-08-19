"""Observe canonical deep-market record completion without changing provider behavior.

The preserved primary market-evidence probe uses a dedicated
``ThreadPoolExecutor(thread_name_prefix='deep-market-evidence')`` for independent record
work. Spawned certification lanes can legitimately outlive the ordinary stall budget while
that work is still completing, so this module scopes an executor subclass to the disposable
child process and reports only genuinely completed record futures.

Progress is attached to ``Future`` completion rather than ordered ``Executor.map``
consumption. This is important because ``map`` preserves input order: one slow early record
must not hide later completed work from the no-progress supervisor. The canonical iterator,
task order, result order, provider behavior, evidence rules, market membership, thresholds,
CIO authority, construction, execution, and paper-only controls remain unchanged.
"""

from __future__ import annotations

import threading
from typing import Callable, Mapping, Sequence

from operations import comprehensive_market_discovery_legacy as legacy
from operations.certification_work_progress import record_certification_work_progress


_PROGRESS_RECORD_INTERVAL = 4
_DEEP_EXECUTOR_PREFIX = "deep-market-evidence"


def run_with_canonical_work_progress(
    delegate: Callable[[Sequence[object], object, object], Mapping[str, object]],
    *,
    records: Sequence[object],
    timestamp: object,
    policy: object,
    asset_class: str,
) -> Mapping[str, object]:
    """Run one unchanged lane probe while exposing actual completed primary work."""

    governed_records = tuple(records)
    total_records = len(governed_records)
    original_executor = legacy.ThreadPoolExecutor
    completion_lock = threading.Lock()
    completed_records = [0]
    emitted_records = [0]

    def record_completion(*, force: bool = False) -> None:
        """Publish only newly completed work; never manufacture a timer heartbeat."""

        payload: tuple[int, int] | None = None
        with completion_lock:
            completed = completed_records[0]
            pending_delta = completed - emitted_records[0]
            if pending_delta <= 0:
                return
            if not force and pending_delta < _PROGRESS_RECORD_INTERVAL:
                return
            emitted_records[0] = completed
            payload = (min(completed, total_records), pending_delta)
        assert payload is not None
        processed, delta = payload
        record_certification_work_progress(
            asset_class,
            processed_records=processed,
            total_records=total_records,
            chunk_records=delta,
        )

    def future_completed(future) -> None:
        # Cancellation is not completed evidence work. A future that terminates with an
        # exception is still a completed canonical work unit; the exception itself remains
        # fail-closed and propagates through the unchanged ``map`` iterator immediately
        # when its ordered result is consumed.
        if future.cancelled():
            return
        with completion_lock:
            completed_records[0] += 1
        record_completion()

    class ProgressAwareExecutor(original_executor):
        def submit(self, fn, /, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            if str(getattr(self, "_thread_name_prefix", "")) == _DEEP_EXECUTOR_PREFIX:
                future.add_done_callback(future_completed)
            return future

    # Install only inside the disposable spawned lane. The preserved primary probe imports
    # this executor from ``comprehensive_market_discovery_legacy`` and ``Executor.map``
    # dispatches through ``self.submit``. We do not override ``map`` itself, so its canonical
    # ordered-result semantics are byte-for-byte the standard-library behavior.
    legacy.ThreadPoolExecutor = ProgressAwareExecutor
    try:
        return delegate(governed_records, timestamp, policy)
    finally:
        # A normal canonical executor context has joined every submitted future by here.
        # Flush a final remainder only when real completions occurred since the last batch.
        record_completion(force=True)
        legacy.ThreadPoolExecutor = original_executor


__all__ = ["run_with_canonical_work_progress"]
