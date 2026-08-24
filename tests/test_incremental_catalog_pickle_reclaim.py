from __future__ import annotations

import hashlib

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker


def test_catalog_checkpoint_writer_bounds_dirty_cache_window(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(worker, "_CATALOG_PERSIST_CHECKPOINT_BYTES", 64)
    fsync_calls: list[int] = []
    advice_calls: list[tuple[int, int, int, int]] = []
    checkpoints: list[int] = []
    advice = 4

    monkeypatch.setattr(worker.os, "fsync", lambda fd: fsync_calls.append(fd))
    monkeypatch.setattr(worker.os, "POSIX_FADV_DONTNEED", advice, raising=False)
    monkeypatch.setattr(
        worker.os,
        "posix_fadvise",
        lambda fd, offset, length, value: advice_calls.append(
            (fd, offset, length, value)
        ),
        raising=False,
    )

    payload = b"x" * 257
    path = tmp_path / "catalog.tmp"
    with path.open("wb") as handle:
        writer = worker._CatalogCheckpointWriter(
            handle,
            checkpoint=checkpoints.append,
        )
        assert writer.write(payload) == len(payload)
        writer.flush()
        digest = writer.digest.hexdigest()
        byte_count = writer.byte_count

    assert path.read_bytes() == payload
    assert byte_count == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert checkpoints == [64, 128, 192, 256]
    assert len(fsync_calls) == 4
    assert [(offset, length) for _, offset, length, _ in advice_calls] == [
        (0, 64),
        (64, 64),
        (128, 64),
        (192, 64),
    ]
    assert all(value == advice for _, _, _, value in advice_calls)


def test_catalog_checkpoint_advice_is_fail_soft_but_checkpoint_continues(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(worker, "_CATALOG_PERSIST_CHECKPOINT_BYTES", 32)
    monkeypatch.delattr(worker.os, "posix_fadvise", raising=False)
    checkpoints: list[int] = []

    path = tmp_path / "portable.tmp"
    with path.open("wb") as handle:
        writer = worker._CatalogCheckpointWriter(
            handle,
            checkpoint=checkpoints.append,
        )
        writer.write(b"y" * 65)
        writer.flush()

    assert path.read_bytes() == b"y" * 65
    assert checkpoints == [32, 64]


def test_catalog_lane_reclaims_during_pickle_serialization_and_restores_writer(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(worker, "_CATALOG_PERSIST_CHECKPOINT_BYTES", 64)
    phases: list[str] = []
    descriptor_holder: list[object] = []
    original_hashing_writer = worker._legacy._HashingWriter

    monkeypatch.setattr(
        worker,
        "_release_catalog_lane_reference_cache",
        lambda values, *, phase: (),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values, *, phase="handoff": phases.append(phase) or None,
    )
    monkeypatch.setattr(worker, "_safe_reclaim_log", lambda *args, **kwargs: None)

    payload = b"international-equity" * 64

    def fake_catalog_stage(request_path, values, *, asset_class_value, index):
        del request_path, values
        descriptor_holder.append(
            worker._legacy._write_pickle_blob(
                tmp_path,
                f"raw-catalog-{index:03d}-{asset_class_value}.pkl",
                payload,
            )
        )

    monkeypatch.setattr(worker._lane_local, "_catalog_lane_stage", fake_catalog_stage)

    worker._catalog_lane_stage(
        tmp_path / "request.json",
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        asset_class_value="international_equity",
        index=4,
    )

    assert phases[0] == "pre_persist"
    assert "during_persist" in phases
    assert phases[-1] == "post_persist"
    assert worker._legacy._HashingWriter is original_hashing_writer
    descriptor = descriptor_holder[0]
    assert worker._legacy._load_pickle_blob(tmp_path, descriptor) == payload


def test_incremental_catalog_repair_preserves_governed_boundaries() -> None:
    assert worker._DEFAULT_MEMORY_HIGH_WATER_FRACTION == 0.70
    assert worker._DEFAULT_MEMORY_RESERVE_MB == 640.0
    assert worker._CATALOG_HANDOFF_RECLAIM_MARGIN_KIB == 32 * 1024
    assert worker._CATALOG_PERSIST_CHECKPOINT_BYTES == 8 * 1024 * 1024
