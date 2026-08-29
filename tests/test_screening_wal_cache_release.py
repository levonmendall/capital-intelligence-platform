from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import screening.resilient_store as resilient_store
from screening import ScreeningEventType


AS_OF = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)


def _append_start(store, *, payload: dict[str, object] | None = None):
    return store.append(
        event_identifier="screening:wal-cache:start",
        cycle_identifier="screening:wal-cache",
        event_type=ScreeningEventType.CYCLE_STARTED,
        occurred_at=AS_OF,
        payload={"state": "started"} if payload is None else payload,
    )


def test_successful_screening_commit_releases_wal_before_database_cache(
    tmp_path, monkeypatch
) -> None:
    store = resilient_store.SQLiteFullUniverseScreeningStore(tmp_path / "screening.db")
    advised: list[Path] = []
    monkeypatch.setattr(
        resilient_store,
        "_flush_and_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    event = _append_start(store)

    assert event.event_identifier == "screening:wal-cache:start"
    assert advised == [Path(f"{store.path}-wal"), store.path]
    assert store.verify_integrity() is True


def test_failed_screening_transaction_never_publishes_cache_release(
    tmp_path, monkeypatch
) -> None:
    store = resilient_store.SQLiteFullUniverseScreeningStore(tmp_path / "screening.db")
    _append_start(store)
    advised: list[Path] = []
    monkeypatch.setattr(
        resilient_store,
        "_flush_and_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    with pytest.raises(ValueError, match="identifier cannot be reused"):
        _append_start(store, payload={"state": "different"})

    assert advised == []
    assert store.verify_integrity() is True


def test_cache_advice_failure_is_fail_soft_for_screening_commit(
    tmp_path, monkeypatch
) -> None:
    store = resilient_store.SQLiteFullUniverseScreeningStore(tmp_path / "screening.db")

    def unavailable(_path: Path) -> bool:
        raise OSError("cache advice unavailable")

    monkeypatch.setattr(
        resilient_store,
        "_flush_and_advise_file_cache_dontneed",
        unavailable,
    )

    event = _append_start(store)

    assert event.event_identifier == "screening:wal-cache:start"
    assert store.verify_integrity() is True


def test_committed_cache_helper_flushes_before_dontneed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "screening.db-wal"
    path.write_bytes(b"committed-screening-pages")
    calls: list[str] = []

    monkeypatch.setattr(
        resilient_store.os,
        "fsync",
        lambda _descriptor: calls.append("fsync"),
    )
    monkeypatch.setattr(
        resilient_store.os,
        "POSIX_FADV_DONTNEED",
        4,
        raising=False,
    )
    monkeypatch.setattr(
        resilient_store.os,
        "posix_fadvise",
        lambda _descriptor, _offset, _length, _advice: calls.append("dontneed"),
        raising=False,
    )

    assert resilient_store._flush_and_advise_file_cache_dontneed(path) is True
    assert calls == ["fsync", "dontneed"]
    assert path.read_bytes() == b"committed-screening-pages"
