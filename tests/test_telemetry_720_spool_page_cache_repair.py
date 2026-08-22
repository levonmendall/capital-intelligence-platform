from __future__ import annotations

import errno
import hashlib

from operations import comprehensive_discovery_input_spool as spool


def _install_fadvise_recorder(monkeypatch):
    calls: list[tuple[int, int, int, int]] = []
    advice = 4

    def fake_fadvise(fd: int, offset: int, length: int, value: int) -> None:
        calls.append((fd, offset, length, value))

    monkeypatch.setattr(spool.os, "POSIX_FADV_DONTNEED", advice, raising=False)
    monkeypatch.setattr(spool.os, "posix_fadvise", fake_fadvise, raising=False)
    return calls, advice


def test_pickle_spool_is_durable_integrity_preserving_and_cache_shedding(
    tmp_path,
    monkeypatch,
) -> None:
    advice_calls, advice = _install_fadvise_recorder(monkeypatch)
    fsync_calls: list[int] = []
    monkeypatch.setattr(spool.os, "fsync", lambda fd: fsync_calls.append(fd))

    payload = tuple(
        {
            "symbol": f"INTL-{index:05d}",
            "asset_class": "international_equity",
            "ordinal": index,
        }
        for index in range(2_000)
    )
    descriptor = spool._write_pickle_blob(tmp_path, "lane.pkl", payload)
    raw = (tmp_path / descriptor.relative_path).read_bytes()

    assert descriptor.byte_count == len(raw)
    assert descriptor.sha256 == hashlib.sha256(raw).hexdigest()
    assert spool._load_pickle_blob(tmp_path, descriptor) == payload
    assert fsync_calls
    # One advisory after the write, one after integrity verification, and one after
    # deserialization.  All operate on the complete file and preserve the descriptor.
    assert len(advice_calls) >= 3
    assert all(offset == 0 and length == 0 for _, offset, length, _ in advice_calls)
    assert all(value == advice for _, _, _, value in advice_calls)


def test_bytes_spool_uses_same_durable_cache_lifecycle(tmp_path, monkeypatch) -> None:
    advice_calls, advice = _install_fadvise_recorder(monkeypatch)
    fsync_calls: list[int] = []
    monkeypatch.setattr(spool.os, "fsync", lambda fd: fsync_calls.append(fd))

    payload = b"policy-evidence" * 4096
    descriptor = spool._write_bytes_blob(tmp_path, "policy.pkl", payload)

    assert (tmp_path / "policy.pkl").read_bytes() == payload
    assert descriptor.byte_count == len(payload)
    assert descriptor.sha256 == hashlib.sha256(payload).hexdigest()
    assert fsync_calls
    assert advice_calls == [(advice_calls[0][0], 0, 0, advice)]


def test_cache_advice_is_best_effort_on_unsupported_filesystems(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(spool.os, "POSIX_FADV_DONTNEED", 4, raising=False)

    def unsupported(*_args) -> None:
        raise OSError(errno.EINVAL, "fadvise unsupported")

    monkeypatch.setattr(spool.os, "posix_fadvise", unsupported, raising=False)
    payload = ("BTC", "ETH", "SOL")

    descriptor = spool._write_pickle_blob(tmp_path, "fallback.pkl", payload)

    assert spool._load_pickle_blob(tmp_path, descriptor) == payload


def test_cache_advice_absence_preserves_fail_closed_spool_behavior(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delattr(spool.os, "posix_fadvise", raising=False)
    payload = tuple(range(128))

    descriptor = spool._write_pickle_blob(tmp_path, "portable.pkl", payload)
    assert spool._load_pickle_blob(tmp_path, descriptor) == payload

    corrupted = bytearray((tmp_path / "portable.pkl").read_bytes())
    corrupted[-1] ^= 0x01
    (tmp_path / "portable.pkl").write_bytes(corrupted)

    try:
        spool._load_pickle_blob(tmp_path, descriptor)
    except spool.ComprehensiveDiscoverySpoolError as error:
        assert "integrity mismatch" in str(error)
    else:
        raise AssertionError("corrupted spool evidence must fail closed")


def test_page_cache_repair_does_not_add_any_authority() -> None:
    assert spool._authority_fields() == {
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
