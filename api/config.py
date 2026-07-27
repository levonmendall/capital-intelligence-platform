"""Environment-backed configuration for the Capital Intelligence API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


def _path(value: str | None, *, default: Path) -> Path:
    return Path(value).expanduser() if value else default


def _optional(value: str | None) -> str | None:
    return None if value is None or not value.strip() else value.strip()


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Versioned runtime settings with secure production defaults."""

    snapshot_database: Path = Path("database/daily_intelligence_snapshots.db")
    portfolio_database: Path = Path("database/capital_intelligence.db")
    investor_memory_database: Path = Path("database/investor_memory.db")
    identity_database: Path = Path("database/identity.db")
    alert_database: Path | None = None
    journal_database: Path = Path("database/institutional_journal.db")
    full_universe_screening_database: Path = Path("database/full_universe_screening.db")
    canonical_cycle_context_provider: str | None = None
    replay_directory: Path | None = Path("database/decision_replays")
    authentication_required: bool = False
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    password_minimum_length: int = 12
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = field(default=None, repr=False)
    bootstrap_admin_name: str = "Platform Administrator"
    scheduler_timezone: str = "America/New_York"
    scheduler_hour: int = 7
    scheduler_poll_seconds: int = 60
    scheduler_retry_minutes: int = 15
    scheduler_lease_minutes: int = 30
    alert_maximum_attempts: int = 4
    alert_retry_minutes: int = 5
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = field(default=None, repr=False)
    smtp_from_address: str | None = None
    smtp_use_tls: bool = True
    require_journal: bool = False
    require_live_provider: bool = False
    allowed_origins: tuple[str, ...] = ()
    history_default_limit: int = 30
    history_max_limit: int = 100
    conviction_default_lookback: int = 7
    conviction_max_lookback: int = 30
    application_name: str = "Capital Intelligence API"
    application_version: str = "1.3.0"

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_database",
            "portfolio_database",
            "investor_memory_database",
            "identity_database",
            "journal_database",
            "full_universe_screening_database",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Path):
                raise TypeError(f"{field_name} must be a pathlib.Path")
        if self.alert_database is not None and not isinstance(
            self.alert_database,
            Path,
        ):
            raise TypeError("alert_database must be a pathlib.Path or None")
        if self.replay_directory is not None and not isinstance(
            self.replay_directory,
            Path,
        ):
            raise TypeError("replay_directory must be a pathlib.Path or None")
        if self.canonical_cycle_context_provider is not None:
            provider = self.canonical_cycle_context_provider.strip()
            if not provider or ":" not in provider:
                raise ValueError(
                    "canonical_cycle_context_provider must use module:function form"
                )
            object.__setattr__(
                self,
                "canonical_cycle_context_provider",
                provider,
            )
        if not 1 <= self.access_token_minutes <= 1440:
            raise ValueError("access_token_minutes must be between 1 and 1440")
        if not 1 <= self.refresh_token_days <= 365:
            raise ValueError("refresh_token_days must be between 1 and 365")
        if self.refresh_token_days * 1440 <= self.access_token_minutes:
            raise ValueError("refresh token lifetime must exceed access token lifetime")
        if not 10 <= self.password_minimum_length <= 128:
            raise ValueError("password_minimum_length must be between 10 and 128")
        if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
            raise ValueError(
                "bootstrap administrator email and password must be supplied together"
            )
        if not self.bootstrap_admin_name.strip():
            raise ValueError("bootstrap_admin_name cannot be empty")
        if not self.scheduler_timezone.strip():
            raise ValueError("scheduler_timezone cannot be empty")
        if not 0 <= self.scheduler_hour <= 23:
            raise ValueError("scheduler_hour must be between 0 and 23")
        if not 1 <= self.scheduler_poll_seconds <= 3600:
            raise ValueError("scheduler_poll_seconds must be between 1 and 3600")
        if not 1 <= self.scheduler_retry_minutes <= 1440:
            raise ValueError("scheduler_retry_minutes must be between 1 and 1440")
        if not 1 <= self.scheduler_lease_minutes <= 1440:
            raise ValueError("scheduler_lease_minutes must be between 1 and 1440")
        if not 1 <= self.alert_maximum_attempts <= 20:
            raise ValueError("alert_maximum_attempts must be between 1 and 20")
        if not 1 <= self.alert_retry_minutes <= 1440:
            raise ValueError("alert_retry_minutes must be between 1 and 1440")
        if not 1 <= self.smtp_port <= 65535:
            raise ValueError("smtp_port must be between 1 and 65535")
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError("SMTP username and password must be supplied together")
        if self.smtp_host and not self.smtp_from_address:
            raise ValueError("smtp_from_address is required when smtp_host is configured")
        if self.smtp_from_address and "@" not in self.smtp_from_address:
            raise ValueError("smtp_from_address must be a valid email address")
        if not 1 <= self.history_default_limit <= self.history_max_limit:
            raise ValueError(
                "history_default_limit must be between 1 and history_max_limit"
            )
        if not 1 <= self.history_max_limit <= 1000:
            raise ValueError("history_max_limit must be between 1 and 1000")
        if not 2 <= self.conviction_default_lookback <= self.conviction_max_lookback:
            raise ValueError(
                "conviction_default_lookback must be between 2 and conviction_max_lookback"
            )
        if not 2 <= self.conviction_max_lookback <= 90:
            raise ValueError("conviction_max_lookback must be between 2 and 90")
        for value in self.allowed_origins:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("allowed_origins must contain non-empty strings")
        if not self.application_name.strip():
            raise ValueError("application_name cannot be empty")
        if not self.application_version.strip():
            raise ValueError("application_version cannot be empty")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ApiSettings":
        """Load settings without mutating process environment."""

        values = os.environ if environ is None else environ
        data_dir = Path(
            values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
        ).expanduser()
        replay_value = values.get("CAPITAL_INTELLIGENCE_REPLAY_DIRECTORY")
        replay_directory = (
            None
            if replay_value is not None and not replay_value.strip()
            else _path(
                replay_value,
                default=data_dir / "decision_replays",
            )
        )
        origins = tuple(
            item.strip()
            for item in values.get(
                "CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS",
                "",
            ).split(",")
            if item.strip()
        )
        return cls(
            snapshot_database=_path(
                values.get("CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE"),
                default=data_dir / "daily_intelligence_snapshots.db",
            ),
            portfolio_database=_path(
                values.get("CAPITAL_INTELLIGENCE_PORTFOLIO_DATABASE"),
                default=data_dir / "capital_intelligence.db",
            ),
            investor_memory_database=_path(
                values.get("CAPITAL_INTELLIGENCE_INVESTOR_MEMORY_DATABASE"),
                default=data_dir / "investor_memory.db",
            ),
            identity_database=_path(
                values.get("CAPITAL_INTELLIGENCE_IDENTITY_DATABASE"),
                default=data_dir / "identity.db",
            ),
            alert_database=_path(
                values.get("CAPITAL_INTELLIGENCE_ALERT_DATABASE"),
                default=data_dir / "alerts.db",
            ),
            journal_database=_path(
                values.get("CAPITAL_INTELLIGENCE_JOURNAL_DATABASE"),
                default=data_dir / "institutional_journal.db",
            ),
            full_universe_screening_database=_path(
                values.get(
                    "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
                ),
                default=data_dir / "full_universe_screening.db",
            ),
            canonical_cycle_context_provider=_optional(
                values.get("CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER")
            ),
            replay_directory=replay_directory,
            authentication_required=_boolean(
                values.get("CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED"),
                default=True,
            ),
            access_token_minutes=int(
                values.get("CAPITAL_INTELLIGENCE_ACCESS_TOKEN_MINUTES", "15")
            ),
            refresh_token_days=int(
                values.get("CAPITAL_INTELLIGENCE_REFRESH_TOKEN_DAYS", "30")
            ),
            password_minimum_length=int(
                values.get("CAPITAL_INTELLIGENCE_PASSWORD_MINIMUM_LENGTH", "12")
            ),
            bootstrap_admin_email=_optional(
                values.get("CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL")
            ),
            bootstrap_admin_password=_optional(
                values.get("CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD")
            ),
            bootstrap_admin_name=values.get(
                "CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_NAME",
                "Platform Administrator",
            ),
            scheduler_timezone=values.get(
                "CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE",
                "America/New_York",
            ),
            scheduler_hour=int(
                values.get("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7")
            ),
            scheduler_poll_seconds=int(
                values.get("CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS", "60")
            ),
            scheduler_retry_minutes=int(
                values.get("CAPITAL_INTELLIGENCE_SCHEDULER_RETRY_MINUTES", "15")
            ),
            scheduler_lease_minutes=int(
                values.get("CAPITAL_INTELLIGENCE_SCHEDULER_LEASE_MINUTES", "30")
            ),
            alert_maximum_attempts=int(
                values.get("CAPITAL_INTELLIGENCE_ALERT_MAXIMUM_ATTEMPTS", "4")
            ),
            alert_retry_minutes=int(
                values.get("CAPITAL_INTELLIGENCE_ALERT_RETRY_MINUTES", "5")
            ),
            smtp_host=_optional(values.get("CAPITAL_INTELLIGENCE_SMTP_HOST")),
            smtp_port=int(values.get("CAPITAL_INTELLIGENCE_SMTP_PORT", "587")),
            smtp_username=_optional(
                values.get("CAPITAL_INTELLIGENCE_SMTP_USERNAME")
            ),
            smtp_password=_optional(
                values.get("CAPITAL_INTELLIGENCE_SMTP_PASSWORD")
            ),
            smtp_from_address=_optional(
                values.get("CAPITAL_INTELLIGENCE_SMTP_FROM_ADDRESS")
            ),
            smtp_use_tls=_boolean(
                values.get("CAPITAL_INTELLIGENCE_SMTP_USE_TLS"),
                default=True,
            ),
            require_journal=_boolean(
                values.get("CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL")
            ),
            require_live_provider=_boolean(
                values.get("CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER")
            ),
            allowed_origins=origins,
            history_default_limit=int(
                values.get("CAPITAL_INTELLIGENCE_HISTORY_DEFAULT_LIMIT", "30")
            ),
            history_max_limit=int(
                values.get("CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT", "100")
            ),
            conviction_default_lookback=int(
                values.get("CAPITAL_INTELLIGENCE_CONVICTION_DEFAULT_LOOKBACK", "7")
            ),
            conviction_max_lookback=int(
                values.get("CAPITAL_INTELLIGENCE_CONVICTION_MAX_LOOKBACK", "30")
            ),
            application_name=values.get(
                "CAPITAL_INTELLIGENCE_API_NAME",
                "Capital Intelligence API",
            ),
            application_version=values.get(
                "CAPITAL_INTELLIGENCE_API_VERSION",
                "1.3.0",
            ),
        )


__all__ = ["ApiSettings"]
