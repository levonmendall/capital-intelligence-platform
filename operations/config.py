"""Environment-backed operational hardening settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _boolean(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _optional(value: str | None) -> str | None:
    return None if value is None or not value.strip() else value.strip()


@dataclass(frozen=True, slots=True)
class OperationalSettings:
    """Deployment, telemetry, backup, and request-safety settings."""

    environment: str = "development"
    log_level: str = "INFO"
    json_logs: bool = True
    service_name: str = "capital-intelligence-api"
    release: str = "development"
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    enforce_https: bool = False
    max_request_bytes: int = 1_048_576
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    metrics_token: str | None = None
    worker_heartbeat_path: Path = Path("database/worker-heartbeat.json")
    worker_max_age_seconds: int = 180
    backup_directory: Path = Path("backups")
    backup_retention_days: int = 14
    backup_interval_hours: int = 24
    backup_encryption_key: str | None = None
    require_encrypted_backups: bool = False

    def __post_init__(self) -> None:
        environment = self.environment.strip().lower()
        if environment not in {"development", "test", "staging", "production"}:
            raise ValueError("environment must be development, test, staging, or production")
        object.__setattr__(self, "environment", environment)
        level = self.log_level.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level is invalid")
        object.__setattr__(self, "log_level", level)
        if not self.service_name.strip():
            raise ValueError("service_name cannot be empty")
        if not self.release.strip():
            raise ValueError("release cannot be empty")
        hosts = tuple(dict.fromkeys(item.strip() for item in self.allowed_hosts if item.strip()))
        if not hosts:
            raise ValueError("allowed_hosts cannot be empty")
        object.__setattr__(self, "allowed_hosts", hosts)
        if not 1_024 <= self.max_request_bytes <= 100 * 1024 * 1024:
            raise ValueError("max_request_bytes must be between 1 KiB and 100 MiB")
        if not 1 <= self.rate_limit_requests <= 100_000:
            raise ValueError("rate_limit_requests must be between 1 and 100000")
        if not 1 <= self.rate_limit_window_seconds <= 3_600:
            raise ValueError("rate_limit_window_seconds must be between 1 and 3600")
        if not 10 <= self.worker_max_age_seconds <= 86_400:
            raise ValueError("worker_max_age_seconds must be between 10 and 86400")
        if not 1 <= self.backup_retention_days <= 3_650:
            raise ValueError("backup_retention_days must be between 1 and 3650")
        if not 1 <= self.backup_interval_hours <= 168:
            raise ValueError("backup_interval_hours must be between 1 and 168")
        for field_name in ("worker_heartbeat_path", "backup_directory"):
            if not isinstance(getattr(self, field_name), Path):
                raise TypeError(f"{field_name} must be a pathlib.Path")
        if self.require_encrypted_backups and not self.backup_encryption_key:
            raise ValueError("backup_encryption_key is required for encrypted backups")
        if environment == "production":
            if not self.enforce_https:
                raise ValueError("production requires enforce_https=true")
            if "*" in hosts:
                raise ValueError("production cannot use a wildcard allowed host")
            if not self.metrics_token or len(self.metrics_token) < 24:
                raise ValueError("production requires a metrics token of at least 24 characters")
            if not self.require_encrypted_backups:
                raise ValueError("production requires encrypted backups")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "OperationalSettings":
        values = os.environ if environ is None else environ
        hosts = tuple(
            item.strip()
            for item in values.get(
                "CAPITAL_INTELLIGENCE_ALLOWED_HOSTS",
                "localhost,127.0.0.1,testserver",
            ).split(",")
            if item.strip()
        )
        data_dir = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
        return cls(
            environment=values.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "development"),
            log_level=values.get("CAPITAL_INTELLIGENCE_LOG_LEVEL", "INFO"),
            json_logs=_boolean(values.get("CAPITAL_INTELLIGENCE_JSON_LOGS"), default=True),
            service_name=values.get(
                "CAPITAL_INTELLIGENCE_SERVICE_NAME",
                "capital-intelligence-api",
            ),
            release=values.get("CAPITAL_INTELLIGENCE_RELEASE", "development"),
            allowed_hosts=hosts,
            enforce_https=_boolean(values.get("CAPITAL_INTELLIGENCE_ENFORCE_HTTPS")),
            max_request_bytes=int(
                values.get("CAPITAL_INTELLIGENCE_MAX_REQUEST_BYTES", "1048576")
            ),
            rate_limit_requests=int(
                values.get("CAPITAL_INTELLIGENCE_RATE_LIMIT_REQUESTS", "120")
            ),
            rate_limit_window_seconds=int(
                values.get("CAPITAL_INTELLIGENCE_RATE_LIMIT_WINDOW_SECONDS", "60")
            ),
            metrics_token=_optional(values.get("CAPITAL_INTELLIGENCE_METRICS_TOKEN")),
            worker_heartbeat_path=Path(
                values.get(
                    "CAPITAL_INTELLIGENCE_WORKER_HEARTBEAT_PATH",
                    str(data_dir / "worker-heartbeat.json"),
                )
            ).expanduser(),
            worker_max_age_seconds=int(
                values.get("CAPITAL_INTELLIGENCE_WORKER_MAX_AGE_SECONDS", "180")
            ),
            backup_directory=Path(
                values.get("CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY", "backups")
            ).expanduser(),
            backup_retention_days=int(
                values.get("CAPITAL_INTELLIGENCE_BACKUP_RETENTION_DAYS", "14")
            ),
            backup_interval_hours=int(
                values.get("CAPITAL_INTELLIGENCE_BACKUP_INTERVAL_HOURS", "24")
            ),
            backup_encryption_key=_optional(
                values.get("CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY")
            ),
            require_encrypted_backups=_boolean(
                values.get("CAPITAL_INTELLIGENCE_REQUIRE_ENCRYPTED_BACKUPS"),
                default=False,
            ),
        )


__all__ = ["OperationalSettings"]
