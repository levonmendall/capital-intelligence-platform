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
from typing import Any, Mapping, Sequence

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
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise BackupError(f"cannot open SQLite database {path.name}") from error
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as error:
        raise BackupError(f"SQLite integrity check failed for {path.name}") from error
    finally:
        connection.close()
    if row is None or row[0] != "ok":
        raise BackupError(f"SQLite integrity check failed for {path.name}")


def _text(value: object, *, field_name: str, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized or None


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SQLiteBackupManager:
    def __init__(
        self,
        sources: Mapping[str, str | Path],
        destination: str | Path,
        *,
        encryption_key: str | bytes | None = None,
        require_encryption: bool = False,
        retention_days: int = 14,
        required_sources: Sequence[str] = (),
        source_metadata: Mapping[str, Mapping[str, object]] | None = None,
        prohibited_sources: Sequence[str] = (),
        baseline_identifier: str | None = None,
        process_version: str | None = None,
        code_version: str | None = None,
        registry_schema_version: str | None = None,
        clock=None,
    ) -> None:
        self.sources = {str(name): Path(path) for name, path in sources.items()}
        self.destination = Path(destination)
        self.require_encryption = require_encryption
        self.retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.required_sources = tuple(str(item) for item in required_sources)
        self.prohibited_sources = frozenset(str(item) for item in prohibited_sources)
        self.source_metadata = {
            str(name): dict(metadata)
            for name, metadata in (source_metadata or {}).items()
        }
        self.baseline_identifier = _text(
            baseline_identifier,
            field_name="baseline_identifier",
            required=False,
        )
        self.process_version = _text(
            process_version,
            field_name="process_version",
            required=False,
        )
        self.code_version = _text(
            code_version,
            field_name="code_version",
            required=False,
        )
        self.registry_schema_version = _text(
            registry_schema_version,
            field_name="registry_schema_version",
            required=False,
        )
        logical_names = tuple(self.sources)
        if any(not name.strip() for name in logical_names):
            raise ValueError("backup source logical names cannot be empty")
        if len(logical_names) != len(set(logical_names)):
            raise ValueError("backup source logical names must be unique")
        if len(self.required_sources) != len(set(self.required_sources)):
            raise ValueError("required_sources cannot contain duplicates")
        missing_definitions = set(self.required_sources) - set(self.sources)
        if missing_definitions:
            raise ValueError(
                "required backup sources are not defined: "
                f"{sorted(missing_definitions)}"
            )
        extra_metadata = set(self.source_metadata) - set(self.sources)
        if extra_metadata:
            raise ValueError(
                "backup metadata references undefined sources: "
                f"{sorted(extra_metadata)}"
            )
        prohibited = set(self.sources) & self.prohibited_sources
        if prohibited:
            raise ValueError(
                "prohibited legacy authorities cannot enter active backups: "
                f"{sorted(prohibited)}"
            )
        if require_encryption and not encryption_key:
            raise ValueError("encryption_key is required")
        if encryption_key is None:
            self._fernet = None
        else:
            key = (
                encryption_key.encode("ascii")
                if isinstance(encryption_key, str)
                else encryption_key
            )
            try:
                self._fernet = Fernet(key)
            except (TypeError, ValueError) as error:
                raise ValueError("encryption_key must be a valid Fernet key") from error
        if retention_days < 1:
            raise ValueError("retention_days must be positive")

    @property
    def strict_manifest(self) -> bool:
        return bool(
            self.required_sources
            or self.source_metadata
            or self.prohibited_sources
            or self.baseline_identifier
            or self.process_version
            or self.code_version
            or self.registry_schema_version
        )

    def validate_sources(self) -> dict[str, object]:
        available: list[str] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        for logical_name, source in sorted(self.sources.items()):
            if source.is_file():
                try:
                    _verify_database(source)
                except BackupError as error:
                    if logical_name in self.required_sources:
                        missing_required.append(f"{logical_name}: {error}")
                    else:
                        missing_optional.append(f"{logical_name}: {error}")
                else:
                    available.append(logical_name)
            elif logical_name in self.required_sources:
                missing_required.append(logical_name)
            else:
                missing_optional.append(logical_name)
        return {
            "status": "valid" if not missing_required else "blocked",
            "available": available,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "required": list(self.required_sources),
            "prohibited_present": sorted(set(self.sources) & self.prohibited_sources),
            "schema_version": "canonical-backup-source-validation.v1",
        }

    def _manifest_entry(
        self,
        *,
        logical_name: str,
        source: Path,
        target: Path,
    ) -> dict[str, object]:
        entry: dict[str, object] = {
            "logical_name": logical_name,
            "filename": target.name,
            "sha256": _sha256(target),
            "bytes": target.stat().st_size,
        }
        metadata = self.source_metadata.get(logical_name)
        if metadata:
            entry.update(metadata)
        entry.setdefault("configured_path", str(source))
        entry.setdefault("required", logical_name in self.required_sources)
        return entry

    def create_backup(self) -> BackupResult:
        validation = self.validate_sources()
        missing_required = validation["missing_required"]
        if missing_required:
            raise BackupError(
                "required canonical backup authorities are unavailable: "
                f"{missing_required}"
            )
        self.destination.mkdir(parents=True, exist_ok=True)
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise BackupError("backup clock must return a timezone-aware timestamp")
        stamp = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with tempfile.TemporaryDirectory(
            prefix="capital-intelligence-backup-"
        ) as temporary:
            root = Path(temporary)
            entries: list[dict[str, object]] = []
            omitted_optional: list[str] = []
            for logical_name, source in sorted(self.sources.items()):
                if not source.is_file():
                    omitted_optional.append(logical_name)
                    continue
                target = root / f"{logical_name}.sqlite3"
                try:
                    source_connection = sqlite3.connect(
                        f"file:{source}?mode=ro",
                        uri=True,
                    )
                    target_connection = sqlite3.connect(target)
                    try:
                        source_connection.backup(target_connection)
                    finally:
                        target_connection.close()
                        source_connection.close()
                except sqlite3.Error as error:
                    raise BackupError(
                        f"failed to copy SQLite authority {logical_name}"
                    ) from error
                _verify_database(target)
                entries.append(
                    self._manifest_entry(
                        logical_name=logical_name,
                        source=source,
                        target=target,
                    )
                )
            if not entries:
                raise BackupError("no SQLite databases were available to back up")
            if self.strict_manifest:
                manifest: dict[str, object] = {
                    "schema_version": "capital-intelligence-backup.v2",
                    "created_at": timestamp.astimezone(timezone.utc).isoformat(),
                    "baseline_identifier": self.baseline_identifier,
                    "process_version": self.process_version,
                    "code_version": self.code_version,
                    "registry_schema_version": self.registry_schema_version,
                    "required_logical_names": list(self.required_sources),
                    "prohibited_logical_names": sorted(self.prohibited_sources),
                    "omitted_optional_logical_names": omitted_optional,
                    "files": entries,
                }
                manifest["authority_set_sha256"] = hashlib.sha256(
                    "|".join(
                        sorted(str(entry["logical_name"]) for entry in entries)
                    ).encode("utf-8")
                ).hexdigest()
            else:
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
                    archive.add(
                        root / str(entry["filename"]),
                        arcname=str(entry["filename"]),
                    )
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
                raise BackupError(
                    "backup decryption or authentication failed"
                ) from error
            plain = temporary / archive.name.removesuffix(".fernet")
            plain.write_bytes(content)
            return plain
        return archive

    def _validate_manifest(self, manifest: Mapping[str, object]) -> list[Mapping[str, object]]:
        schema = manifest.get("schema_version")
        if schema not in {
            "capital-intelligence-backup.v1",
            "capital-intelligence-backup.v2",
        }:
            raise BackupError("backup schema is unsupported")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise BackupError("backup manifest contains no database files")
        if not all(isinstance(item, Mapping) for item in entries):
            raise BackupError("backup file entries must encode objects")
        logical_names = [str(item.get("logical_name") or "") for item in entries]
        filenames = [str(item.get("filename") or "") for item in entries]
        if any(not item for item in logical_names) or len(logical_names) != len(
            set(logical_names)
        ):
            raise BackupError("backup logical authority names are invalid or duplicated")
        if any(not item for item in filenames) or len(filenames) != len(set(filenames)):
            raise BackupError("backup filenames are invalid or duplicated")
        if schema == "capital-intelligence-backup.v2":
            required = manifest.get("required_logical_names")
            prohibited = manifest.get("prohibited_logical_names")
            if not isinstance(required, list) or not all(
                isinstance(item, str) and item.strip() for item in required
            ):
                raise BackupError("version-2 backup required authority set is invalid")
            if len(required) != len(set(required)):
                raise BackupError("version-2 required authority set contains duplicates")
            if not isinstance(prohibited, list) or not all(
                isinstance(item, str) and item.strip() for item in prohibited
            ):
                raise BackupError("version-2 prohibited authority set is invalid")
            missing = sorted(set(required) - set(logical_names))
            forbidden = sorted(set(prohibited) & set(logical_names))
            if missing:
                raise BackupError(
                    f"backup is missing required canonical authorities: {missing}"
                )
            if forbidden:
                raise BackupError(
                    f"backup contains prohibited legacy authorities: {forbidden}"
                )
            expected_digest = hashlib.sha256(
                "|".join(sorted(logical_names)).encode("utf-8")
            ).hexdigest()
            if manifest.get("authority_set_sha256") != expected_digest:
                raise BackupError("backup authority-set digest is invalid")
            if self.required_sources and set(required) != set(self.required_sources):
                raise BackupError(
                    "backup required-authority set does not match the active registry"
                )
            if self.prohibited_sources and not self.prohibited_sources.issubset(
                set(prohibited)
            ):
                raise BackupError(
                    "backup prohibited-authority policy does not match active policy"
                )
        elif self.required_sources:
            raise BackupError(
                "legacy version-1 backup cannot satisfy canonical recovery policy"
            )
        return entries

    def verify_archive(self, archive: str | Path) -> dict[str, object]:
        source = Path(archive)
        if not source.exists():
            raise BackupError("backup archive was not found")
        with tempfile.TemporaryDirectory(
            prefix="capital-intelligence-verify-"
        ) as temporary:
            root = Path(temporary)
            materialized = self._materialize_archive(source, root)
            try:
                with tarfile.open(materialized, "r:gz") as bundle:
                    members = bundle.getmembers()
                    if any(
                        member.name.startswith("/")
                        or ".." in Path(member.name).parts
                        for member in members
                    ):
                        raise BackupError("backup contains an unsafe path")
                    bundle.extractall(root / "extracted", filter="data")
            except (tarfile.TarError, OSError) as error:
                raise BackupError("backup archive is invalid") from error
            extracted = root / "extracted"
            manifest_path = extracted / "manifest.json"
            if not manifest_path.exists():
                raise BackupError("backup manifest is missing")
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise BackupError("backup manifest is invalid JSON") from error
            if not isinstance(manifest, Mapping):
                raise BackupError("backup manifest must encode an object")
            entries = self._validate_manifest(manifest)
            for entry in entries:
                database = extracted / str(entry["filename"])
                if not database.exists() or _sha256(database) != entry.get("sha256"):
                    raise BackupError(
                        f"backup checksum failed for {entry['filename']}"
                    )
                _verify_database(database)
            return dict(manifest)

    def latest_backup_health(
        self,
        *,
        maximum_age_seconds: int,
        minimum_archive_bytes: int = 1,
    ) -> tuple[bool, str, Path | None]:
        """Verify that the newest archive is recent, policy-compliant, and valid."""

        if maximum_age_seconds < 1:
            raise ValueError("maximum_age_seconds must be positive")
        if minimum_archive_bytes < 1:
            raise ValueError("minimum_archive_bytes must be positive")
        if not self.destination.exists():
            return False, "backup directory does not exist", None
        candidates = sorted(
            self.destination.glob("capital-intelligence-*.tar.gz*"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return False, "no backup archive exists", None
        latest = candidates[0]
        if latest.stat().st_size < minimum_archive_bytes:
            return False, f"latest backup archive is empty: {latest.name}", latest
        if self.require_encryption and latest.suffix != ".fernet":
            return False, f"latest backup is not encrypted: {latest.name}", latest
        try:
            manifest = self.verify_archive(latest)
            created_at_value = manifest.get("created_at")
            if not isinstance(created_at_value, str):
                raise BackupError("backup manifest creation time is missing")
            created_at = datetime.fromisoformat(created_at_value)
            if created_at.tzinfo is None:
                raise BackupError("backup manifest creation time has no timezone")
        except (BackupError, OSError, ValueError, KeyError, TypeError) as error:
            return False, f"latest backup failed verification: {error}", latest
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age_seconds = (
            now.astimezone(timezone.utc) - created_at.astimezone(timezone.utc)
        ).total_seconds()
        if age_seconds < -300:
            return False, "latest backup creation time is in the future", latest
        if age_seconds > maximum_age_seconds:
            return (
                False,
                f"latest backup is stale: age_seconds={int(age_seconds)}",
                latest,
            )
        return (
            True,
            (
                f"latest backup verified: {latest.name}; "
                f"age_seconds={max(0, int(age_seconds))}; "
                f"files={len(manifest['files'])}; "
                f"schema={manifest['schema_version']}"
            ),
            latest,
        )

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
        verified = self.verify_archive(source)
        with tempfile.TemporaryDirectory(
            prefix="capital-intelligence-restore-"
        ) as temporary:
            root = Path(temporary)
            materialized = self._materialize_archive(source, root)
            with tarfile.open(materialized, "r:gz") as bundle:
                bundle.extractall(root / "extracted", filter="data")
            extracted = root / "extracted"
            restored: list[Path] = []
            for entry in verified["files"]:
                source_database = extracted / str(entry["filename"])
                if _sha256(source_database) != entry["sha256"]:
                    raise BackupError(
                        f"backup checksum failed for {entry['filename']}"
                    )
                _verify_database(source_database)
                destination = target_root / str(entry["filename"])
                if destination.exists() and not overwrite:
                    raise BackupError(
                        f"restore target already exists: {destination}"
                    )
                temporary_target = destination.with_suffix(
                    destination.suffix + ".restore"
                )
                shutil.copy2(source_database, temporary_target)
                _verify_database(temporary_target)
                temporary_target.replace(destination)
                restored.append(destination)
            if len(restored) != len(verified["files"]):
                raise BackupError("restore did not reproduce the complete authority set")
            return tuple(restored)

    def prune(self) -> tuple[Path, ...]:
        if not self.destination.exists():
            return ()
        cutoff = self._clock() - timedelta(days=self.retention_days)
        removed: list[Path] = []
        for candidate in self.destination.glob(
            "capital-intelligence-*.tar.gz*"
        ):
            modified = datetime.fromtimestamp(
                candidate.stat().st_mtime,
                timezone.utc,
            )
            if modified < cutoff:
                candidate.unlink()
                removed.append(candidate)
        return tuple(removed)


__all__ = ["BackupError", "BackupResult", "SQLiteBackupManager"]
