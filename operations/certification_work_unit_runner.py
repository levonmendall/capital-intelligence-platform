"""Observe canonical deep-market record completion without changing provider behavior.

The preserved primary market-evidence probe uses a dedicated
``ThreadPoolExecutor(thread_name_prefix='deep-market-evidence')`` for independent record
work. Spawned certification lanes can legitimately outlive the ordinary stall budget while
that work is still completing, so this module scopes an executor subclass to the disposable
child process and reports only completed mapped records.

No provider call, task order, result order, market membership, evidence rule, threshold,
CIO authority, construction, execution, or paper-only control is changed.
"""

from __future__ import annotations

from collections.abc import Sized
from typing import Callable, Mapping, Sequence

from operations import comprehensive_market_discovery_legacy as legacy
from operations.certification_work_progress import record_certification_work_progress


_PROGRESS_RECORD_INTERVAL = 4


def run_with_canonical_work_progress(
    delegate: Callable[[Sequence[object], object, object], Mapping[str, object]],
    *,
    records: Sequence[object],
    timestamp: object,
    policy: object,
    asset_class: str,
) -> Mapping[str, object]:
    """Run one unchanged lane probe while exposing completed primary record work."""

    governed_records = tuple(records)
    total_records = len(governed_records)
    original_executor = legacy.ThreadPoolExecutor
    processed_records = [0]

    class ProgressAwareExecutor(original_executor):
        def map(self, fn, *iterables, **kwargs):
            mapped = super().map(fn, *iterables, **kwargs)
            if str(getattr(self, "_thread_name_prefix", "")) != "deep-market-evidence":
                return mapped
            first_iterable = iterables[0] if iterables else ()
            map_total = len(first_iterable) if isinstance(first_iterable, Sized) else None
            map_completed = 0
            last_emitted = 0

            def completed_results():
                nonlocal map_completed, last_emitted
                for result in mapped:
                    map_completed += 1
                    processed_records[0] += 1
                    should_emit = (
                        map_completed % _PROGRESS_RECORD_INTERVAL == 0
                        or (map_total is not None and map_completed == map_total)
                    )
                    if should_emit:
                        delta = map_completed - last_emitted
                        last_emitted = map_completed
                        record_certification_work_progress(
                            asset_class,
                            processed_records=min(processed_records[0], total_records),
                            total_records=total_records,
                            chunk_records=delta,
                        )
                    yield result
                # ``map_total`` is normally known because the canonical probe supplies a
                # tuple. Preserve a final real-completion event for any future sizedness-
                # neutral iterable without manufacturing periodic time-based heartbeats.
                if map_completed > last_emitted:
                    record_certification_work_progress(
                        asset_class,
                        processed_records=min(processed_records[0], total_records),
                        total_records=total_records,
                        chunk_records=map_completed - last_emitted,
                    )

            return completed_results()

    legacy.ThreadPoolExecutor = ProgressAwareExecutor
    try:
        return delegate(governed_records, timestamp, policy)
    finally:
        legacy.ThreadPoolExecutor = original_executor


__all__ = ["run_with_canonical_work_progress"]
