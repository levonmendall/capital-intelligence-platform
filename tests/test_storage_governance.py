from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import storage_governance
from storage_governance import (
    StorageCapacityError,
    install_persistent_history_storage_governance,
    preflight_storage_capacity,
)

_MIB = 1024 * 1024
_GIB = 1024 * _MIB


def _sqlite_cache(path, payload_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE cache_payload(value BLOB NOT NULL)")
        connection.execute(
            "INSERT INTO cache_payload(value) VALUES(zeroblob(?))", (payload_bytes,)
        )
        connection.commit()
    finally:
        connection.close()


def _no_projected_headroom() -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_REFERENCE_PUBLISH_HEADROOM_MB": "0",
        "CAPITAL_INTELLIGENCE_RUNTIME_WORKSPACE_HEADROOM_MB": "0",
    }


def test_preflight_resets_only_oversized_rebuildable_history_cache(tmp_path) -> None:
    database = tmp_path / "historical_evidence" / "market_history.sqlite3"
    canonical = tmp_path / "canonical" / "portfolio.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("authoritative", encoding="utf-8")
    _sqlite_cache(database, 2 * _MIB)

    snapshot = preflight_storage_capacity(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1",
            "CAPITAL_INTELLIGENCE_HISTORICAL_CACHE_MAX_MB": "1",
            **_no_projected_headroom(),
        }
    )

    assert snapshot is not None
    assert snapshot.historical_cache_reset is True
    assert snapshot.historical_cache_bytes == 0
    assert not database.exists()
    assert canonical.read_text(encoding="utf-8") == "authoritative"


def test_preflight_fails_closed_when_safe_reclamation_cannot_restore_reserve(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "historical_evidence" / "market_history.sqlite3"
    canonical = tmp_path / "canonical" / "portfolio.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("authoritative", encoding="utf-8")
    _sqlite_cache(database, 2 * _MIB)

    monkeypatch.setattr(
        storage_governance.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=10 * _GIB,
            used=(10 * _GIB) - (128 * _MIB),
            free=128 * _MIB,
        ),
    )

    with pytest.raises(StorageCapacityError, match="insufficient"):
        preflight_storage_capacity(
            {
                "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
                "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1024",
                "CAPITAL_INTELLIGENCE_HISTORICAL_CACHE_MAX_MB": "4096",
                **_no_projected_headroom(),
            }
        )

    assert not database.exists()
    assert canonical.read_text(encoding="utf-8") == "authoritative"


def test_preflight_accounts_for_projected_all_market_working_set(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        storage_governance.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=25 * _GIB,
            used=19 * _GIB,
            free=6 * _GIB,
        ),
    )

    with pytest.raises(StorageCapacityError, match="required_free_bytes") as captured:
        preflight_storage_capacity(
            {
                "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
                "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1024",
                "CAPITAL_INTELLIGENCE_REFERENCE_PUBLISH_HEADROOM_MB": "2048",
                "CAPITAL_INTELLIGENCE_RUNTIME_WORKSPACE_HEADROOM_MB": "4096",
            }
        )

    message = str(captured.value)
    assert f"storage_reserve_bytes={1 * _GIB}" in message
    assert f"reference_publish_headroom_bytes={2 * _GIB}" in message
    assert f"runtime_workspace_headroom_bytes={4 * _GIB}" in message


def test_preflight_passes_on_twenty_five_gib_disk_with_projected_headroom(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        storage_governance.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=25 * _GIB,
            used=5 * _GIB,
            free=20 * _GIB,
        ),
    )

    snapshot = preflight_storage_capacity(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1024",
            "CAPITAL_INTELLIGENCE_REFERENCE_PUBLISH_HEADROOM_MB": "2048",
            "CAPITAL_INTELLIGENCE_RUNTIME_WORKSPACE_HEADROOM_MB": "4096",
        }
    )

    assert snapshot is not None
    telemetry = snapshot.telemetry()
    assert telemetry["filesystem_total_mb"] == 25 * 1024
    assert telemetry["filesystem_free_before_mb"] == 20 * 1024
    assert telemetry["filesystem_free_mb"] == 20 * 1024
    assert telemetry["storage_reserve_mb"] == 1024
    assert telemetry["reference_publish_headroom_mb"] == 2048
    assert telemetry["runtime_workspace_headroom_mb"] == 4096
    assert telemetry["required_free_mb"] == 7168


def test_preflight_rejects_workspace_on_different_filesystem(
    tmp_path, monkeypatch
) -> None:
    data_root = tmp_path / "persistent"
    workspace = tmp_path / "runtime"
    data_root.mkdir()
    workspace.mkdir()
    monkeypatch.setattr(
        storage_governance,
        "_same_filesystem",
        lambda _left, _right: False,
    )
    monkeypatch.setattr(
        storage_governance.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=25 * _GIB,
            used=5 * _GIB,
            free=20 * _GIB,
        ),
    )

    with pytest.raises(
        StorageCapacityError,
        match="not on the governed persistent filesystem",
    ):
        preflight_storage_capacity(
            {
                "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
                "TMPDIR": str(workspace),
            }
        )


def test_storage_governance_sets_sqlite_wal_limits_idempotently(tmp_path) -> None:
    class Store:
        def __init__(self) -> None:
            self.path = tmp_path / "historical_evidence" / "market_history.sqlite3"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._values = {
                "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
                "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1",
                "CAPITAL_INTELLIGENCE_HISTORICAL_CACHE_MAX_MB": "64",
                "CAPITAL_INTELLIGENCE_HISTORICAL_WAL_MAX_MB": "8",
                **_no_projected_headroom(),
            }

        def _connect(self):
            return sqlite3.connect(self.path)

        def merge(self, *args, **kwargs):
            return "merged"

    install_persistent_history_storage_governance(Store)
    first_merge = Store.merge
    install_persistent_history_storage_governance(Store)

    assert Store.merge is first_merge
    store = Store()
    connection = store._connect()
    try:
        journal_limit = connection.execute("PRAGMA journal_size_limit").fetchone()[0]
        auto_checkpoint = connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
    finally:
        connection.close()

    assert journal_limit == 8 * _MIB
    assert auto_checkpoint == 1000
