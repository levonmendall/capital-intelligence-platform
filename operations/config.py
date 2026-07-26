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
    security_master_database: Path = Path("database/security_master.db")
    operational_slo_database: Path = Path("database/operational_slos.db")
    require_operational_slos: bool = False
    slo_provider_maximum_age_hours: float = 36.0
    slo_screening_timezone: str = "America/New_York"
    slo_screening_hour: int = 7
    slo_screening_completion_deadline_minutes: int = 120
    slo_thesis_review_grace_hours: float = 24.0
    slo_decision_evaluation_grace_hours: float = 48.0
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
        for field_name in (
            "slo_provider_maximum_age_hours",
            "slo_thesis_review_grace_hours",
            "slo_decision_evaluation_grace_hours",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            if float(value) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if not self.slo_screening_timezone.strip():
            raise ValueError("slo_screening_timezone cannot be empty")
        if isinstance(self.slo_screening_hour, bool) or not isinstance(
            self.slo_screening_hour,
            int,
        ):
            raise TypeError("slo_screening_hour must be an integer")
        if not 0 <= self.slo_screening_hour <= 23:
            raise ValueError("slo_screening_hour must be between 0 and 23")
        if (
            isinstance(self.slo_screening_completion_deadline_minutes, bool)
            or not isinstance(self.slo_screening_completion_deadline_minutes, int)
        ):
            raise TypeError(
                "slo_screening_completion_deadline_minutes must be an integer"
            )
        if not 1 <= self.slo_screening_completion_deadline_minutes <= 1440:
            raise ValueError(
                "slo_screening_completion_deadline_minutes must be between 1 and 1440"
            )
        if not isinstance(self.require_operational_slos, bool):
            raise TypeError("require_operational_slos must be a bool")
        if not 1 <= self.backup_retention_days <= 3_650:
            raise ValueError("backup_retention_days must be between 1 and 3650")
        if not 1 <= self.backup_interval_hours <= 168:
            raise ValueError("backup_interval_hours must be between 1 and 168")
        for field_name in (
            "worker_heartbeat_path",
            "security_master_database",
            "operational_slo_database",
            "backup_directory",
        ):
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
            if not self.require_operational_slos:
                raise ValueError("production requires operational SLO enforcement")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "OperationalSettings":
        values = os.environ if environ is None else environ
        environment = values.get(
            "CAPITAL_INTELLIGENCE_ENVIRONMENT",
            "development",
        )
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
            environment=environment,
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
            security_master_database=Path(
                values.get(
                    "CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATABASE",
                    str(data_dir / "security_master.db"),
                )
            ).expanduser(),
            operational_slo_database=Path(
                values.get(
                    "CAPITAL_INTELLIGENCE_OPERATIONAL_SLO_DATABASE",
                    str(data_dir / "operational_slos.db"),
                )
            ).expanduser(),
            require_operational_slos=_boolean(
                values.get("CAPITAL_INTELLIGENCE_REQUIRE_OPERATIONAL_SLOS"),
                default=environment.strip().lower() == "production",
            ),
            slo_provider_maximum_age_hours=float(
                values.get(
                    "CAPITAL_INTELLIGENCE_SLO_PROVIDER_MAXIMUM_AGE_HOURS",
                    "36",
                )
            ),
            slo_screening_timezone=values.get(
                "CAPITAL_INTELLIGENCE_SLO_SCREENING_TIMEZONE",
                "America/New_York",
            ),
            slo_screening_hour=int(
                values.get("CAPITAL_INTELLIGENCE_SLO_SCREENING_HOUR", "7")
            ),
            slo_screening_completion_deadline_minutes=int(
                values.get(
                    "CAPITAL_INTELLIGENCE_SLO_SCREENING_DEADLINE_MINUTES",
                    "120",
                )
            ),
            slo_thesis_review_grace_hours=float(
                values.get(
                    "CAPITAL_INTELLIGENCE_SLO_THESIS_REVIEW_GRACE_HOURS",
                    "24",
                )
            ),
            slo_decision_evaluation_grace_hours=float(
                values.get(
                    "CAPITAL_INTELLIGENCE_SLO_EVALUATION_GRACE_HOURS",
                    "48",
                )
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
