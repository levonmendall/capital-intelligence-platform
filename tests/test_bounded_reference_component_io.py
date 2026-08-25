from __future__ import annotations

import errno
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import bounded_reference_component_io as bounded_io
from operations import generalized_reference_readiness as generalized


def test_large_component_prefers_direct_io(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "catalog-latest-qualified.json"
    path.write_bytes(b"x" * bounded_io._DIRECT_READ_MIN_BYTES)
    calls: list[str] = []

    def direct(_path: Path) -> bytearray:
        calls.append("direct")
        return bytearray(b'{"ok":true}')

    def sequential(_path: Path):
        raise AssertionError("sequential fallback should not run")

    monkeypatch.setattr(bounded_io, "_read_direct_bytes", direct)
    monkeypatch.setattr(bounded_io, "_read_sequential_bytes", sequential)

    payload, mode, advised, fallback = bounded_io._read_component_bytes(path)

    assert bytes(payload) == b'{"ok":true}'
    assert mode == "direct"
    assert advised == 0
    assert fallback is None
    assert calls == ["direct"]


def test_direct_io_unsupported_falls_back_to_bounded_sequential(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "catalog-latest-qualified.json"
    path.write_bytes(b"x" * bounded_io._DIRECT_READ_MIN_BYTES)

    def unsupported(_path: Path) -> bytearray:
        raise OSError(errno.EINVAL, "direct I/O unsupported")

    monkeypatch.setattr(bounded_io, "_read_direct_bytes", unsupported)
    monkeypatch.setattr(
        bounded_io,
        "_read_sequential_bytes",
        lambda _path: (bytearray(b'{"ok":true}'), 4096),
    )

    payload, mode, advised, fallback = bounded_io._read_component_bytes(path)

    assert bytes(payload) == b'{"ok":true}'
    assert mode == "sequential"
    assert advised == 4096
    assert fallback == "direct_io_OSError_22"


def test_non_support_direct_io_error_remains_fail_closed(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "catalog-latest-qualified.json"
    path.write_bytes(b"x" * bounded_io._DIRECT_READ_MIN_BYTES)

    def broken(_path: Path) -> bytearray:
        raise OSError(errno.EIO, "device read failed")

    monkeypatch.setattr(bounded_io, "_read_direct_bytes", broken)

    try:
        bounded_io._read_component_bytes(path)
    except OSError as error:
        assert error.errno == errno.EIO
    else:
        raise AssertionError("real direct-I/O read failure must not be hidden by fallback")


def test_installed_path_preserves_generalized_integrity_validation(
    monkeypatch, tmp_path: Path
) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    captured_at = datetime.now(timezone.utc)
    lane = CandidateAssetClass.INTERNATIONAL_EQUITY
    records = ({"symbol": "TEST", "asset_class": lane.value},)

    generalized.store_asset_reference_component(
        values,
        asset_class=lane,
        captured_at=captured_at,
        config_fingerprint="cfg",
        coverage=("US",),
        records=records,
        metadata={"collector": "test"},
    )
    original_path_function = generalized.asset_reference_component_path
    monkeypatch.setattr(
        bounded_io,
        "_read_component_bytes",
        lambda path: (bytearray(Path(path).read_bytes()), "test", 0, None),
    )
    try:
        bounded_io.install_bounded_asset_reference_component_io()
        loaded = generalized.load_asset_reference_component(
            values,
            asset_class=lane,
            as_of=captured_at,
            config_fingerprint="cfg",
            coverage=("US",),
        )
        assert loaded is not None
        assert loaded["component_id"]
        assert generalized._component_records(loaded) == list(records)

        component_path = generalized.asset_reference_component_path(values, lane)
        component_path.write_text("{}", encoding="utf-8")
        assert generalized.load_asset_reference_component(
            values,
            asset_class=lane,
            as_of=captured_at,
            config_fingerprint="cfg",
            coverage=("US",),
        ) is None
    finally:
        generalized.asset_reference_component_path = original_path_function
