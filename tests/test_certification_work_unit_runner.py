from __future__ import annotations

import threading
import time

import pytest

from operations import certification_work_progress
from operations import certification_work_unit_runner as work_runner
from operations import comprehensive_market_discovery_legacy as legacy
from operations import redundant_market_probe


def test_primary_deep_executor_completion_publishes_real_record_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, int]]] = []

    monkeypatch.setattr(
        work_runner,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )

    def delegate(records, _timestamp, _policy):
        with legacy.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="deep-market-evidence",
        ) as executor:
            completed = tuple(executor.map(lambda value: value, records))
        return {str(item): object() for item in completed}

    result = work_runner.run_with_canonical_work_progress(
        delegate,
        records=("A", "B", "C", "D", "E"),
        timestamp="epoch",
        policy="policy",
        asset_class="international_equity",
    )

    assert set(result) == {"A", "B", "C", "D", "E"}
    assert published == [
        (
            "international_equity",
            {"processed_records": 4, "total_records": 5, "chunk_records": 4},
        ),
        (
            "international_equity",
            {"processed_records": 5, "total_records": 5, "chunk_records": 1},
        ),
    ]


def test_later_future_completions_are_visible_before_ordered_map_head_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow first record must not hide four genuinely completed later records."""

    published: list[tuple[str, dict[str, int]]] = []
    first_release = threading.Event()
    four_later_completed = threading.Event()
    later_lock = threading.Lock()
    later_count = [0]
    result_holder: dict[str, object] = {}
    error_holder: list[BaseException] = []

    monkeypatch.setattr(
        work_runner,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )

    def work(value: int) -> int:
        if value == 0:
            if not first_release.wait(timeout=5.0):
                raise TimeoutError("test did not release the ordered head future")
            return value
        with later_lock:
            later_count[0] += 1
            if later_count[0] == 4:
                four_later_completed.set()
        return value

    def delegate(records, _timestamp, _policy):
        with legacy.ThreadPoolExecutor(
            max_workers=5,
            thread_name_prefix="deep-market-evidence",
        ) as executor:
            # Standard Executor.map intentionally preserves this input order. The wrapper
            # must observe completion callbacks without changing that result order.
            completed = tuple(executor.map(work, records))
        return {str(item): item for item in completed}

    def run() -> None:
        try:
            result_holder["value"] = work_runner.run_with_canonical_work_progress(
                delegate,
                records=(0, 1, 2, 3, 4),
                timestamp="epoch",
                policy="policy",
                asset_class="international_equity",
            )
        except BaseException as error:  # pragma: no cover - assertion reports below.
            error_holder.append(error)

    thread = threading.Thread(target=run, name="completion-order-progress-test")
    thread.start()
    assert four_later_completed.wait(timeout=2.0)

    # The ordered map consumer is still blocked on record zero, yet four later futures
    # have completed and therefore must already have produced one real progress event.
    assert thread.is_alive()
    assert published == [
        (
            "international_equity",
            {"processed_records": 4, "total_records": 5, "chunk_records": 4},
        )
    ]

    first_release.set()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert error_holder == []
    assert result_holder["value"] == {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4}
    assert published[-1] == (
        "international_equity",
        {"processed_records": 5, "total_records": 5, "chunk_records": 1},
    )


def test_completion_progress_preserves_ordered_exception_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion callbacks must not consume or suppress an out-of-order future error."""

    published: list[tuple[str, dict[str, int]]] = []
    first_release = threading.Event()
    four_later_completed = threading.Event()
    later_lock = threading.Lock()
    later_count = [0]
    error_holder: list[BaseException] = []

    monkeypatch.setattr(
        work_runner,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )

    def work(value: int) -> int:
        if value == 0:
            if not first_release.wait(timeout=5.0):
                raise TimeoutError("test did not release the ordered head future")
            return value
        try:
            if value == 1:
                raise RuntimeError("provider record failed closed")
            return value
        finally:
            with later_lock:
                later_count[0] += 1
                if later_count[0] == 4:
                    four_later_completed.set()

    def delegate(records, _timestamp, _policy):
        with legacy.ThreadPoolExecutor(
            max_workers=5,
            thread_name_prefix="deep-market-evidence",
        ) as executor:
            return tuple(executor.map(work, records))

    def run() -> None:
        try:
            work_runner.run_with_canonical_work_progress(
                delegate,
                records=(0, 1, 2, 3, 4),
                timestamp="epoch",
                policy="policy",
                asset_class="international_equity",
            )
        except BaseException as error:  # expected fail-closed propagation.
            error_holder.append(error)

    thread = threading.Thread(target=run, name="ordered-exception-progress-test")
    thread.start()
    assert four_later_completed.wait(timeout=2.0)

    # The error future and three later successes are finished, but the standard ordered
    # map iterator remains blocked on record zero. Their completion is still observable.
    assert thread.is_alive()
    assert published == [
        (
            "international_equity",
            {"processed_records": 4, "total_records": 5, "chunk_records": 4},
        )
    ]

    first_release.set()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert len(error_holder) == 1
    assert isinstance(error_holder[0], RuntimeError)
    assert str(error_holder[0]) == "provider record failed closed"
    assert published[-1] == (
        "international_equity",
        {"processed_records": 5, "total_records": 5, "chunk_records": 1},
    )


def test_non_deep_executor_does_not_manufacture_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, int]]] = []

    monkeypatch.setattr(
        work_runner,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )

    def delegate(records, _timestamp, _policy):
        with legacy.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="unrelated-work",
        ) as executor:
            tuple(executor.map(lambda value: value, records))
        return {}

    assert work_runner.run_with_canonical_work_progress(
        delegate,
        records=("A", "B"),
        timestamp="epoch",
        policy="policy",
        asset_class="international_equity",
    ) == {}
    assert published == []


def test_silent_delegate_does_not_manufacture_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, int]]] = []

    monkeypatch.setattr(
        work_runner,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )

    def delegate(_records, _timestamp, _policy):
        time.sleep(0.05)
        return {}

    assert work_runner.run_with_canonical_work_progress(
        delegate,
        records=("A",),
        timestamp="epoch",
        policy="policy",
        asset_class="international_equity",
    ) == {}
    assert published == []


def test_work_progress_uses_transport_only_diagnostic_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, int], dict[str, str]]] = []

    def capture(stage, *, metrics=None, values=None):
        calls.append((stage, dict(metrics or {}), dict(values or {})))
        return None

    monkeypatch.setattr(
        certification_work_progress.diagnostic,
        "record_manual_cio_diagnostic_progress",
        capture,
    )

    certification_work_progress.record_certification_work_progress(
        "crypto",
        processed_records=4,
        total_records=10,
        chunk_records=2,
        evidence_complete_records=3,
    )

    assert calls == [
        (
            "deep_market_evidence:crypto",
            {
                "processed_records": 4,
                "total_records": 10,
                "chunk_records": 2,
                "evidence_complete_records": 3,
            },
            {
                "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "false"
            },
        )
    ]


def test_spawned_fallback_progress_never_invokes_shared_diagnostic_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, int]]] = []
    callback_calls: list[str] = []

    def original_progress(*_args, **_kwargs):
        callback_calls.append("shared-writer")

    monkeypatch.setattr(
        redundant_market_probe,
        "_record_deep_progress",
        original_progress,
    )
    monkeypatch.setattr(
        certification_work_progress,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )

    certification_work_progress.install_spawn_child_transport_only_progress()
    redundant_market_probe._record_deep_progress(
        "fx",
        decision_eligible_records=40,
        processed_records=16,
        evidence_complete_records=12,
        callback=lambda *_args, **_kwargs: callback_calls.append("callback"),
    )
    redundant_market_probe._record_deep_progress(
        "fx",
        decision_eligible_records=40,
        processed_records=32,
        evidence_complete_records=25,
        callback=lambda *_args, **_kwargs: callback_calls.append("callback"),
    )

    assert callback_calls == []
    assert published == [
        (
            "fx",
            {
                "processed_records": 16,
                "total_records": 40,
                "chunk_records": 16,
                "evidence_complete_records": 12,
            },
        ),
        (
            "fx",
            {
                "processed_records": 32,
                "total_records": 40,
                "chunk_records": 16,
                "evidence_complete_records": 25,
            },
        ),
    ]
