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
        connection.execute("INSERT INTO cache_payload(value) VALUES(zeroblob(?))", (payload_bytes,))
        connection.commit()
    finally:
        connection.close()


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
        lambda _path: SimpleNamespace(total=10 * _GIB, used=(10 * _GIB) - (128 * _MIB), free=128 * _MIB),
    )

    with pytest.raises(StorageCapacityError, match="insufficient"):
        preflight_storage_capacity(
            {
                "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
                "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1024",
                "CAPITAL_INTELLIGENCE_HISTORICAL_CACHE_MAX_MB": "4096",
            }
        )

    assert not database.exists()
    assert canonical.read_text(encoding="utf-8") == "authoritative"


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
