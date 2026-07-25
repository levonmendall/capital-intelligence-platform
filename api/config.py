"""Environment-backed configuration for the Capital Intelligence API."""

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


def _path(value: str | None, *, default: Path) -> Path:
    return Path(value).expanduser() if value else default


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Versioned runtime settings with safe local defaults."""

    snapshot_database: Path = Path("database/daily_intelligence_snapshots.db")
    portfolio_database: Path = Path("database/capital_intelligence.db")
    journal_database: Path = Path("database/institutional_journal.db")
    replay_directory: Path | None = Path("database/decision_replays")
    require_journal: bool = False
    require_live_provider: bool = False
    allowed_origins: tuple[str, ...] = ()
    history_default_limit: int = 30
    history_max_limit: int = 100
    application_name: str = "Capital Intelligence API"
    application_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_database",
            "portfolio_database",
            "journal_database",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Path):
                raise TypeError(f"{field_name} must be a pathlib.Path")
        if self.replay_directory is not None and not isinstance(
            self.replay_directory,
            Path,
        ):
            raise TypeError("replay_directory must be a pathlib.Path or None")
        if not 1 <= self.history_default_limit <= self.history_max_limit:
            raise ValueError(
                "history_default_limit must be between 1 and history_max_limit"
            )
        if not 1 <= self.history_max_limit <= 1000:
            raise ValueError("history_max_limit must be between 1 and 1000")
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
            journal_database=_path(
                values.get("CAPITAL_INTELLIGENCE_JOURNAL_DATABASE"),
                default=data_dir / "institutional_journal.db",
            ),
            replay_directory=replay_directory,
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
            application_name=values.get(
                "CAPITAL_INTELLIGENCE_API_NAME",
                "Capital Intelligence API",
            ),
            application_version=values.get(
                "CAPITAL_INTELLIGENCE_API_VERSION",
                "1.0.0",
            ),
        )


__all__ = ["ApiSettings"]
