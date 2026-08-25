"""Bound file-cache lifetime for persistent lane-scoped reference component reads.

Large governed asset-reference components are immutable JSON files. Reading several of
those files sequentially during comprehensive discovery can leave clean pages charged to
the service cgroup even after each finite catalog child exits. This module changes only
the physical read path: large components prefer Linux direct I/O so their bytes do not
enter the page cache, while unsupported filesystems fall back to bounded sequential reads
that advise each completed aligned prefix ``DONTNEED``.

The existing generalized-reference loader still performs schema, integrity, freshness,
coverage, and paper-only validation byte-for-byte. This module has no evidence,
candidate, CIO, construction, sizing, execution, or real-money authority.
"""

from __future__ import annotations

import errno
import locale
import mmap
import os
from pathlib import Path
from typing import Mapping


_DIRECT_READ_MIN_BYTES = 8 * 1024 * 1024
_DIRECT_READ_CHUNK_BYTES = 8 * 1024 * 1024
_SEQUENTIAL_READ_CHUNK_BYTES = 4 * 1024 * 1024
_BASE_PATH = type(Path())
_DIRECT_UNSUPPORTED_ERRNOS = frozenset(
    value
    for value in (
        errno.EINVAL,
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOTSUP", None),
        errno.EPERM,
    )
    if isinstance(value, int)
)


def _safe_log(event: str, **details: object) -> None:
    """Emit credential-safe operational telemetry without making logging authoritative."""

    try:
        from operations import reclaimable_memory_guard as memory_guard

        memory_guard._safe_log(event, **details)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        pass


def _alignment_and_chunk(fd: int, *, target_bytes: int) -> tuple[int, int]:
    try:
        block_size = int(getattr(os.fstat(fd), "st_blksize", 0) or 0)
    except (OSError, TypeError, ValueError):
        block_size = 0
    alignment = max(4096, block_size)
    chunk = max(alignment, int(target_bytes))
    chunk = ((chunk + alignment - 1) // alignment) * alignment
    return alignment, chunk


def _read_direct_bytes(path: Path) -> bytearray:
    """Read one large immutable file with ``O_DIRECT`` when Linux/filesystem permit it."""

    direct = getattr(os, "O_DIRECT", None)
    readv = getattr(os, "readv", None)
    if not isinstance(direct, int) or direct == 0 or not callable(readv):
        raise OSError(errno.EOPNOTSUPP, "direct I/O is unavailable")

    fd = os.open(path, os.O_RDONLY | direct)
    try:
        _alignment, chunk_size = _alignment_and_chunk(
            fd, target_bytes=_DIRECT_READ_CHUNK_BYTES
        )
        buffer = mmap.mmap(-1, chunk_size)
        view = memoryview(buffer)
        payload = bytearray()
        try:
            while True:
                count = readv(fd, [view])
                if count <= 0:
                    break
                payload.extend(view[:count])
                if count < chunk_size:
                    break
        finally:
            view.release()
            buffer.close()
        return payload
    finally:
        os.close(fd)


def _advise(fd: int, *, offset: int, length: int, advice: int | None) -> bool:
    fadvise = getattr(os, "posix_fadvise", None)
    if not callable(fadvise) or not isinstance(advice, int):
        return False
    try:
        fadvise(fd, offset, length, advice)
    except (OSError, ValueError):
        return False
    return True


def _read_sequential_bytes(path: Path) -> tuple[bytearray, int]:
    """Fallback reader that drops each completed aligned read prefix as it advances."""

    fd = os.open(path, os.O_RDONLY)
    advised_bytes = 0
    try:
        alignment, chunk_size = _alignment_and_chunk(
            fd, target_bytes=_SEQUENTIAL_READ_CHUNK_BYTES
        )
        _advise(
            fd,
            offset=0,
            length=0,
            advice=getattr(os, "POSIX_FADV_SEQUENTIAL", None),
        )
        dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
        payload = bytearray()
        consumed = 0
        advised_offset = 0
        while True:
            chunk = os.read(fd, chunk_size)
            if not chunk:
                break
            payload.extend(chunk)
            consumed += len(chunk)
            aligned_end = (consumed // alignment) * alignment
            if aligned_end > advised_offset and _advise(
                fd,
                offset=advised_offset,
                length=aligned_end - advised_offset,
                advice=dontneed,
            ):
                advised_bytes += aligned_end - advised_offset
                advised_offset = aligned_end
        if consumed > advised_offset:
            _advise(
                fd,
                offset=advised_offset,
                length=0,
                advice=dontneed,
            )
        return payload, advised_bytes
    finally:
        os.close(fd)


def _read_component_bytes(path: Path) -> tuple[bytearray, str, int, str | None]:
    """Prefer cache-bypassing reads for large components; retain a safe portable fallback."""

    try:
        byte_count = int(path.stat().st_size)
    except OSError:
        byte_count = -1

    fallback_reason: str | None = None
    if byte_count >= _DIRECT_READ_MIN_BYTES:
        try:
            return _read_direct_bytes(path), "direct", 0, None
        except OSError as error:
            if error.errno not in _DIRECT_UNSUPPORTED_ERRNOS:
                raise
            fallback_reason = f"direct_io_{type(error).__name__}_{error.errno}"

    payload, advised_bytes = _read_sequential_bytes(path)
    return payload, "sequential", advised_bytes, fallback_reason


def _bounded_read_text(
    path: Path,
    *,
    encoding: str | None,
    errors: str | None,
) -> str:
    payload, mode, advised_bytes, fallback_reason = _read_component_bytes(path)
    codec = encoding or locale.getpreferredencoding(False)
    text = payload.decode(codec, errors or "strict")
    _safe_log(
        "asset_reference_component_bounded_read",
        asset_reference_component_file=path.name,
        asset_reference_component_bytes=len(payload),
        asset_reference_component_read_mode=mode,
        asset_reference_component_cache_advised_bytes=advised_bytes,
        asset_reference_component_direct_fallback_reason=fallback_reason,
        decision_authority=False,
        candidate_authority=False,
        sizing_authority=False,
        construction_authority=False,
        execution_authority=False,
        paper_only=True,
        real_money_authorized=False,
        advisory_only=True,
    )
    return text


class _BoundedAssetReferencePath(_BASE_PATH):
    """Path subtype whose text reads avoid retaining large component file-cache pages."""

    def read_text(
        self,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        return _bounded_read_text(self, encoding=encoding, errors=errors)


def install_bounded_asset_reference_component_io() -> None:
    """Install a stable path seam while leaving generalized validation unchanged."""

    from operations import generalized_reference_readiness as generalized

    current = generalized.asset_reference_component_path
    if getattr(current, "_bounded_reference_component_io", False):
        return

    original = current

    def bounded_asset_reference_component_path(
        values: Mapping[str, str],
        asset_class,
        *,
        scope: str = generalized._CATALOG_SCOPE,
    ) -> Path:
        path = original(values, asset_class, scope=scope)
        return _BoundedAssetReferencePath(path)

    setattr(bounded_asset_reference_component_path, "_bounded_reference_component_io", True)
    setattr(bounded_asset_reference_component_path, "_original", original)
    generalized.asset_reference_component_path = bounded_asset_reference_component_path


__all__ = ("install_bounded_asset_reference_component_io",)
