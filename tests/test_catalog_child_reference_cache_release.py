from __future__ import annotations

import inspect

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker
from operations import comprehensive_market_discovery as facade
from operations import lane_local_comprehensive_discovery_spool as lane_local


def test_catalog_child_reclaims_around_raw_catalog_and_defers_completion(
    monkeypatch,
    tmp_path,
) -> None:
    order: list[str] = []

    def final_progress(stage: str, *args, **kwargs):
        del args, kwargs
        order.append(f"progress:{stage}")

    monkeypatch.setattr(
        facade._core,
        "record_manual_cio_diagnostic_progress",
        final_progress,
    )
    monkeypatch.setattr(
        worker,
        "_release_catalog_lane_reference_cache",
        lambda values, *, phase: order.append(f"cache:{phase}") or (),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values, *, phase="handoff": order.append(f"reclaim:{phase}") or None,
    )

    def fake_write(directory, name, value):
        del directory, value
        order.append(f"write:{name}")
        return object()

    monkeypatch.setattr(worker._legacy, "_write_pickle_blob", fake_write)

    def fake_catalog_stage(request_path, values, *, asset_class_value, index):
        del request_path, values
        worker._legacy._write_pickle_blob(
            tmp_path,
            f"raw-catalog-{index:03d}-{asset_class_value}.pkl",
            ("record",),
        )
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
        "cache:pre_persist",
        "reclaim:pre_persist",
        "write:raw-catalog-004-international_equity.pkl",
        "reclaim:post_persist",
        "state:persisted",
    ]
    assert worker._legacy._write_pickle_blob is fake_write
    assert facade._core.record_manual_cio_diagnostic_progress is final_progress


def test_durable_catalog_state_precedes_completion_progress():
    source = inspect.getsource(lane_local._catalog_lane_stage)
    assert source.index("_write_stage_state(") < source.index(
        "record_manual_cio_diagnostic_progress("
    )


def test_catalog_child_reclaim_is_scoped_to_raw_catalog_pickle():
    source = inspect.getsource(worker._catalog_lane_stage)
    assert "expected_blob" in source
    assert source.index(
        '_release_catalog_lane_reference_cache(values, phase="pre_persist")'
    ) < source.index("descriptor = original_write_pickle_blob(directory, name, value)")
    assert source.index(
        "descriptor = original_write_pickle_blob(directory, name, value)"
    ) < source.index(
        '_reclaim_catalog_lane_cgroup_cache(values, phase="post_persist")'
    )
    assert "catalog_lane_completion_deferred" in source
