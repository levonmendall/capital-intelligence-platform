from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import FunctionType
import time

import pytest

from operations import certification_work_unit_runner as work_runner


def _named_function(module_name: str, function_name: str):
    def template(value):
        return value

    code = template.__code__.replace(co_name=function_name)
    return FunctionType(code, {"__name__": module_name})


def test_worker_thread_record_completion_publishes_real_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, int]]] = []

    def capture(asset_class: str, **metrics) -> None:
        published.append((asset_class, dict(metrics)))

    monkeypatch.setattr(work_runner, "record_certification_work_progress", capture)
    build_record_features = _named_function(
        "operations.comprehensive_market_discovery_legacy",
        "build_record_features",
    )

    def delegate(records, _timestamp, _policy):
        with ThreadPoolExecutor(max_workers=2) as executor:
            completed = tuple(executor.map(build_record_features, records))
        return {str(item): object() for item in completed}

    result = work_runner.run_with_canonical_work_progress(
        delegate,
        records=("A", "B", "C"),
        timestamp="epoch",
        policy="policy",
        asset_class="international_equity",
    )

    assert set(result) == {"A", "B", "C"}
    assert published
    assert published[-1][0] == "international_equity"
    assert published[-1][1]["processed_records"] == 3
    assert published[-1][1]["total_records"] == 3
    assert sum(item[1]["chunk_records"] for item in published) == 3


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
        time.sleep(work_runner._REPORT_INTERVAL_SECONDS * 1.5)
        return {}

    assert work_runner.run_with_canonical_work_progress(
        delegate,
        records=("A",),
        timestamp="epoch",
        policy="policy",
        asset_class="international_equity",
    ) == {}
    assert published == []


def test_fallback_router_completion_advances_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, int]]] = []

    monkeypatch.setattr(
        work_runner,
        "record_certification_work_progress",
        lambda asset_class, **metrics: published.append((asset_class, dict(metrics))),
    )
    fallback_fetch = _named_function(
        "providers.redundant_market_history",
        "fetch",
    )

    def delegate(records, _timestamp, _policy):
        for item in records:
            fallback_fetch(item)
        return {}

    work_runner.run_with_canonical_work_progress(
        delegate,
        records=("A", "B"),
        timestamp="epoch",
        policy="policy",
        asset_class="fx",
    )

    assert published
    assert published[-1][0] == "fx"
    assert published[-1][1]["processed_records"] == 2
    assert published[-1][1]["total_records"] == 2
