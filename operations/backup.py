"""Consistent, encrypted SQLite backups with manifests and restore verification."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive: Path
    manifest: dict[str, object]
    encrypted: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_database(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if row is None or row[0] != "ok":
        raise BackupError(f"SQLite integrity check failed for {path.name}")


class SQLiteBackupManager:
    def __init__(
        self,
        sources: Mapping[str, str | Path],
        destination: str | Path,
        *,
        encryption_key: str | bytes | None = None,
        require_encryption: bool = False,
        retention_days: int = 14,
        clock=None,
    ) -> None:
        self.sources = {name: Path(path) for name, path in sources.items()}
        self.destination = Path(destination)
        self.require_encryption = require_encryption
        self.retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if require_encryption and not encryption_key:
            raise ValueError("encryption_key is required")
        if encryption_key is None:
            self._fernet = None
        else:
            key = encryption_key.encode("ascii") if isinstance(encryption_key, str) else encryption_key
            try:
                self._fernet = Fernet(key)
            except (TypeError, ValueError) as error:
                raise ValueError("encryption_key must be a valid Fernet key") from error
        if retention_days < 1:
            raise ValueError("retention_days must be positive")

    def create_backup(self) -> BackupResult:
        self.destination.mkdir(parents=True, exist_ok=True)
        timestamp = self._clock()
        stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
        with tempfile.TemporaryDirectory(prefix="capital-intelligence-backup-") as temporary:
            root = Path(temporary)
            entries: list[dict[str, object]] = []
            for logical_name, source in sorted(self.sources.items()):
                if not source.exists():
                    continue
                target = root / f"{logical_name}.sqlite3"
                source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
                target_connection = sqlite3.connect(target)
                try:
                    source_connection.backup(target_connection)
                finally:
                    target_connection.close()
                    source_connection.close()
                _verify_database(target)
                entries.append(
                    {
                        "logical_name": logical_name,
                        "filename": target.name,
                        "sha256": _sha256(target),
                        "bytes": target.stat().st_size,
                    }
                )
            if not entries:
                raise BackupError("no SQLite databases were available to back up")
            manifest = {
                "schema_version": "capital-intelligence-backup.v1",
                "created_at": timestamp.isoformat(),
                "files": entries,
            }
            (root / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            plain_archive = root / f"capital-intelligence-{stamp}.tar.gz"
            with tarfile.open(plain_archive, "w:gz") as archive:
                archive.add(root / "manifest.json", arcname="manifest.json")
                for entry in entries:
                    archive.add(root / str(entry["filename"]), arcname=str(entry["filename"]))
            if self._fernet is None:
                if self.require_encryption:
                    raise BackupError("encrypted backups are required")
                final = self.destination / plain_archive.name
                shutil.copy2(plain_archive, final)
                encrypted = False
            else:
                final = self.destination / f"{plain_archive.name}.fernet"
                final.write_bytes(self._fernet.encrypt(plain_archive.read_bytes()))
                encrypted = True
        self.verify_archive(final)
        self.prune()
        return BackupResult(final, manifest, encrypted)

    def _materialize_archive(self, archive: Path, temporary: Path) -> Path:
        if archive.suffix == ".fernet":
            if self._fernet is None:
                raise BackupError("an encryption key is required to read this backup")
            try:
                content = self._fernet.decrypt(archive.read_bytes())
            except InvalidToken as error:
                raise BackupError("backup decryption or authentication failed") from error
            plain = temporary / archive.name.removesuffix(".fernet")
            plain.write_bytes(content)
            return plain
        return archive

    def verify_archive(self, archive: str | Path) -> dict[str, object]:
        source = Path(archive)
        if not source.exists():
            raise BackupError("backup archive was not found")
        with tempfile.TemporaryDirectory(prefix="capital-intelligence-verify-") as temporary:
            root = Path(temporary)
            materialized = self._materialize_archive(source, root)
            try:
                with tarfile.open(materialized, "r:gz") as bundle:
                    members = bundle.getmembers()
                    if any(member.name.startswith("/") or ".." in Path(member.name).parts for member in members):
                        raise BackupError("backup contains an unsafe path")
                    bundle.extractall(root / "extracted", filter="data")
            except (tarfile.TarError, OSError) as error:
                raise BackupError("backup archive is invalid") from error
            extracted = root / "extracted"
            manifest_path = extracted / "manifest.json"
            if not manifest_path.exists():
                raise BackupError("backup manifest is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != "capital-intelligence-backup.v1":
                raise BackupError("backup schema is unsupported")
            for entry in manifest.get("files", []):
                database = extracted / str(entry["filename"])
                if not database.exists() or _sha256(database) != entry["sha256"]:
                    raise BackupError(f"backup checksum failed for {entry['filename']}")
                _verify_database(database)
            return manifest

    def restore(
        self,
        archive: str | Path,
        target_directory: str | Path,
        *,
        overwrite: bool = False,
    ) -> tuple[Path, ...]:
        source = Path(archive)
        target_root = Path(target_directory)
        target_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="capital-intelligence-restore-") as temporary:
            root = Path(temporary)
            materialized = self._materialize_archive(source, root)
            with tarfile.open(materialized, "r:gz") as bundle:
                bundle.extractall(root / "extracted", filter="data")
            extracted = root / "extracted"
            manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
            restored: list[Path] = []
            for entry in manifest["files"]:
                source_database = extracted / str(entry["filename"])
                if _sha256(source_database) != entry["sha256"]:
                    raise BackupError(f"backup checksum failed for {entry['filename']}")
                _verify_database(source_database)
                destination = target_root / str(entry["filename"])
                if destination.exists() and not overwrite:
                    raise BackupError(f"restore target already exists: {destination}")
                temporary_target = destination.with_suffix(destination.suffix + ".restore")
                shutil.copy2(source_database, temporary_target)
                _verify_database(temporary_target)
                temporary_target.replace(destination)
                restored.append(destination)
            return tuple(restored)

    def prune(self) -> tuple[Path, ...]:
        if not self.destination.exists():
            return ()
        cutoff = self._clock() - timedelta(days=self.retention_days)
        removed: list[Path] = []
        for candidate in self.destination.glob("capital-intelligence-*.tar.gz*"):
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                candidate.unlink()
                removed.append(candidate)
        return tuple(removed)


__all__ = ["BackupError", "BackupResult", "SQLiteBackupManager"]
