from pathlib import Path

import pytest

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker


def test_catalog_child_defers_completion_until_parent_and_restores_recorder(monkeypatch):
    from operations import comprehensive_market_discovery as facade

    observed: list[tuple[str, object]] = []

    def recorder(component, *args, **kwargs):
        observed.append((str(component), kwargs.get("metrics")))

    monkeypatch.setattr(facade._core, "record_manual_cio_diagnostic_progress", recorder)

    def fake_catalog_stage(request_path, values, *, asset_class_value, index):
        facade._core.record_manual_cio_diagnostic_progress(
            "inner_catalog_progress", metrics={"index": index}
        )
        facade._core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_catalog_lane_complete:{asset_class_value}",
            metrics={"catalog_records": 34245, "peak_rss_bytes": 217841664},
        )

    monkeypatch.setattr(worker._lane_local, "_catalog_lane_stage", fake_catalog_stage)
    monkeypatch.setattr(worker, "_safe_reclaim_log", lambda *args, **kwargs: None)

    worker._catalog_lane_stage(
        Path("request.json"),
        {},
        asset_class_value="international_equity",
        index=4,
    )

    assert observed == [("inner_catalog_progress", {"index": 4})]
    assert facade._core.record_manual_cio_diagnostic_progress is recorder


def test_parent_publishes_only_from_matching_durable_state_after_exit(monkeypatch):
    from operations import comprehensive_market_discovery as facade

    events: list[object] = []
    request = {"request_id": "request-1"}
    durable_state = {
        "request_id": "request-1",
        "asset_class": "international_equity",
        "record_count": 34245,
        "peak_rss_bytes": 217841664,
    }

    monkeypatch.setattr(worker._bounded, "_validate_request", lambda path, values: (request, object()))
    monkeypatch.setattr(worker._bounded, "_load_stage_state", lambda path, name: durable_state)
    monkeypatch.setattr(
        worker,
        "_release_catalog_lane_reference_cache",
        lambda values, *, phase: events.append(("release", phase)) or (),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values, *, phase="handoff": events.append(("reclaim", phase)),
    )
    monkeypatch.setattr(worker, "_safe_reclaim_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        facade._core,
        "record_manual_cio_diagnostic_progress",
        lambda component, *, metrics: events.append(("progress", component, metrics)),
    )

    worker._publish_catalog_lane_completion_after_child_exit(
        Path("request.json"),
        {},
        asset_class="international_equity",
        index=4,
    )

    assert events == [
        ("release", "post_child_exit"),
        ("reclaim", "post_child_exit"),
        (
            "progress",
            "bounded_spool_catalog_lane_complete:international_equity",
            {"catalog_records": 34245, "peak_rss_bytes": 217841664},
        ),
    ]


def test_parent_completion_fails_closed_on_durable_state_identity_mismatch(monkeypatch):
    monkeypatch.setattr(
        worker._bounded,
        "_validate_request",
        lambda path, values: ({"request_id": "request-1"}, object()),
    )
    monkeypatch.setattr(
        worker._bounded,
        "_load_stage_state",
        lambda path, name: {
            "request_id": "request-1",
            "asset_class": "future",
            "record_count": 1,
            "peak_rss_bytes": 1,
        },
    )

    with pytest.raises(worker._legacy.ComprehensiveDiscoverySpoolError):
        worker._publish_catalog_lane_completion_after_child_exit(
            Path("request.json"),
            {},
            asset_class="international_equity",
            index=4,
        )


def test_run_stage_waits_for_child_exit_before_parent_completion(monkeypatch):
    events: list[object] = []

    class Process:
        def wait(self):
            events.append("child_exit")
            return 0

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        worker,
        "_publish_catalog_lane_completion_after_child_exit",
        lambda request_path, values, *, asset_class, index: events.append(
            ("parent_completion", asset_class, index)
        ),
    )

    worker.run_stage(
        "catalog-lane",
        Path("request.json"),
        {},
        asset_class="international_equity",
        index=4,
    )

    assert events == [
        "child_exit",
        ("parent_completion", "international_equity", 4),
    ]


def test_run_stage_never_publishes_completion_for_failed_child(monkeypatch):
    published: list[object] = []

    class Process:
        def wait(self):
            return 2

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        worker,
        "_publish_catalog_lane_completion_after_child_exit",
        lambda *args, **kwargs: published.append(True),
    )
    monkeypatch.setattr(
        worker._legacy,
        "load_failure",
        lambda request_path: {
            "failure_stage": "bounded_catalog_lane:international_equity",
            "error_type": "RuntimeError",
            "error_detail": "failed",
        },
    )

    with pytest.raises(worker._legacy.ComprehensiveDiscoverySpoolError):
        worker.run_stage(
            "catalog-lane",
            Path("request.json"),
            {},
            asset_class="international_equity",
            index=4,
        )

    assert published == []


def test_non_catalog_stage_does_not_publish_catalog_completion(monkeypatch):
    published: list[object] = []
    publication_releases: list[object] = []

    class Process:
        def wait(self):
            return 0

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        worker,
        "_publish_catalog_lane_completion_after_child_exit",
        lambda *args, **kwargs: published.append(True),
    )
    monkeypatch.setattr(
        worker,
        "_release_publication_lane_cache_after_child_exit",
        lambda request_path, values, *, asset_class, index: publication_releases.append(
            (asset_class, index)
        ),
    )

    worker.run_stage(
        "publication-lane",
        Path("request.json"),
        {},
        asset_class="international_equity",
        index=4,
    )

    assert published == []
    assert publication_releases == [("international_equity", 4)]


def test_governed_memory_boundaries_remain_unchanged():
    assert worker._DEFAULT_MEMORY_HIGH_WATER_FRACTION == 0.70
    assert worker._DEFAULT_MEMORY_RESERVE_MB == 640.0
    assert worker._CATALOG_HANDOFF_RECLAIM_MARGIN_KIB == 32 * 1024
    assert worker._CATALOG_PERSIST_CHECKPOINT_BYTES == 8 * 1024 * 1024
