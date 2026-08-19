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

            def completed_results():
                for result in mapped:
                    processed_records[0] += 1
                    completed = processed_records[0]
                    if (
                        completed % _PROGRESS_RECORD_INTERVAL == 0
                        or completed == total_records
                    ):
                        record_certification_work_progress(
                            asset_class,
                            processed_records=min(completed, total_records),
                            total_records=total_records,
                            chunk_records=(
                                _PROGRESS_RECORD_INTERVAL
                                if completed % _PROGRESS_RECORD_INTERVAL == 0
                                else completed % _PROGRESS_RECORD_INTERVAL
                            ),
                        )
                    yield result

            return completed_results()

    legacy.ThreadPoolExecutor = ProgressAwareExecutor
    try:
        return delegate(governed_records, timestamp, policy)
    finally:
        legacy.ThreadPoolExecutor = original_executor


__all__ = ["run_with_canonical_work_progress"]
