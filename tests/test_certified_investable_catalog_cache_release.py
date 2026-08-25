from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from operations import certified_investable_catalog as catalog


def _timestamp() -> datetime:
    return datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)


def test_external_catalog_releases_read_cache_after_consumption(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "certified-catalog.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": catalog.SCHEMA_VERSION,
                "complete": True,
                "as_of": "2026-08-25T15:00:00+00:00",
                "available_at": "2026-08-25T15:00:00+00:00",
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    released = []
    monkeypatch.setattr(
        catalog,
        "_advise_read_file_cache_dontneed",
        lambda path: released.append(path) or True,
    )

    assert catalog._external_catalog_records(timestamp=_timestamp(), source=source) == ()
    assert released == [source]


def test_external_catalog_failure_still_releases_read_cache(tmp_path, monkeypatch) -> None:
    source = tmp_path / "certified-catalog.json"
    source.write_text("{", encoding="utf-8")
    released = []
    monkeypatch.setattr(
        catalog,
        "_advise_read_file_cache_dontneed",
        lambda path: released.append(path) or True,
    )

    with pytest.raises(catalog.CertifiedInvestableCatalogError, match="invalid JSON"):
        catalog._external_catalog_records(timestamp=_timestamp(), source=source)

    assert released == [source]


def test_crypto_binding_failure_still_releases_read_cache(tmp_path, monkeypatch) -> None:
    source = tmp_path / "crypto-bindings.json"
    monkeypatch.setenv(catalog.CRYPTO_VENUE_BINDINGS_ENV, str(source))
    released = []
    monkeypatch.setattr(
        catalog,
        "load_crypto_venue_bindings",
        lambda _path: (_ for _ in ()).throw(OSError("read failed")),
    )
    monkeypatch.setattr(
        catalog,
        "_advise_read_file_cache_dontneed",
        lambda path: released.append(path) or True,
    )

    with pytest.raises(
        catalog.CertifiedInvestableCatalogError,
        match="certified multi-venue crypto catalog is unavailable",
    ):
        catalog._certified_crypto_records()

    assert released == [source]


def test_read_cache_advice_is_bounded_and_fail_soft(tmp_path, monkeypatch) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(catalog.os, "POSIX_FADV_DONTNEED", 4, raising=False)
    monkeypatch.setattr(
        catalog.os,
        "posix_fadvise",
        lambda fd, offset, length, advice: calls.append(
            (fd, offset, length, advice)
        ),
        raising=False,
    )

    assert catalog._advise_read_file_cache_dontneed(source) is True
    assert len(calls) == 1
    _fd, offset, length, advice = calls[0]
    assert offset == 0
    assert length == 0
    assert advice == 4

    monkeypatch.setattr(
        catalog.os,
        "posix_fadvise",
        lambda *_args: (_ for _ in ()).throw(OSError("unsupported")),
        raising=False,
    )
    assert catalog._advise_read_file_cache_dontneed(source) is False
