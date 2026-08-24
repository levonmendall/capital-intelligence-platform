from __future__ import annotations

import inspect

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker
from operations import comprehensive_market_discovery as facade
from operations import lane_local_comprehensive_discovery_spool as lane_local


def test_catalog_child_releases_reference_cache_before_completion(monkeypatch, tmp_path):
    order: list[str] = []

    def final_progress(stage: str, *args, **kwargs):
        order.append(f"progress:{stage}")

    monkeypatch.setattr(
        facade._core,
        "record_manual_cio_diagnostic_progress",
        final_progress,
    )
    monkeypatch.setattr(
        worker,
        "release_current_reference_file_cache",
        lambda values: order.append("cache") or (),
    )

    def fake_catalog_stage(request_path, values, *, asset_class_value, index):
        order.append("state:persisted")
        facade._core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_catalog_lane_complete:{asset_class_value}",
            metrics={"catalog_records": 1},
        )

    monkeypatch.setattr(worker._lane_local, "_catalog_lane_stage", fake_catalog_stage)

    worker._catalog_lane_stage(
        tmp_path / "request.json",
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        asset_class_value="international_equity",
        index=4,
    )

    assert order == [
        "state:persisted",
        "cache",
        "progress:bounded_spool_catalog_lane_complete:international_equity",
    ]
    assert facade._core.record_manual_cio_diagnostic_progress is final_progress


def test_durable_catalog_state_precedes_completion_progress():
    source = inspect.getsource(lane_local._catalog_lane_stage)
    assert source.index("_write_stage_state(") < source.index(
        "record_manual_cio_diagnostic_progress("
    )


def test_catalog_child_cache_release_is_completion_scoped():
    source = inspect.getsource(worker._catalog_lane_stage)
    assert 'complete_stage = f"bounded_spool_catalog_lane_complete:{asset_class_value}"' in source
    assert source.index("release_current_reference_file_cache(values)") < source.index(
        "return original_progress(stage, *args, **kwargs)"
    )
