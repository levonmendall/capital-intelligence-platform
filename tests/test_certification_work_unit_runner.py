from __future__ import annotations

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
