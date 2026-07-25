"""Append-only Personal CIO brief history linked to daily and replay records."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from personal_cio.models import PersonalCIOBrief, brief_to_dict


class SQLitePersonalCIOBriefStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.path.exists() and self.path.is_dir():
            raise ValueError("Personal CIO brief path must be a file")
        if not read_only:
            self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS personal_cio_briefs (
                    identifier TEXT PRIMARY KEY,
                    investor_identifier TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    snapshot_identifier TEXT NOT NULL,
                    policy_identifier TEXT,
                    replay_identifiers_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS personal_cio_briefs_investor_as_of
                ON personal_cio_briefs (investor_identifier, as_of DESC);

                CREATE TRIGGER IF NOT EXISTS personal_cio_briefs_prevent_update
                BEFORE UPDATE ON personal_cio_briefs
                BEGIN
                    SELECT RAISE(ABORT, 'Personal CIO brief history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS personal_cio_briefs_prevent_delete
                BEFORE DELETE ON personal_cio_briefs
                BEGIN
                    SELECT RAISE(ABORT, 'Personal CIO brief history is append-only');
                END;
                """
            )

    def append(
        self,
        brief: PersonalCIOBrief,
        *,
        replay_identifiers: tuple[str, ...] = (),
    ) -> dict[str, object]:
        if self.read_only:
            raise PermissionError("Personal CIO brief store is read-only")
        if not isinstance(brief, PersonalCIOBrief):
            raise TypeError("brief must be a PersonalCIOBrief")
        if not isinstance(replay_identifiers, tuple) or not all(
            isinstance(value, str) and value.strip()
            for value in replay_identifiers
        ):
            raise TypeError("replay_identifiers must contain non-empty strings")
        payload = brief_to_dict(brief)
        payload["decision_replays"] = list(replay_identifiers)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM personal_cio_briefs WHERE identifier = ?",
                (brief.identifier,),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != encoded:
                    raise ValueError(
                        "brief identifier already exists with different content"
                    )
                return payload
            connection.execute(
                """
                INSERT INTO personal_cio_briefs (
                    identifier, investor_identifier, as_of,
                    snapshot_identifier, policy_identifier,
                    replay_identifiers_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brief.identifier,
                    brief.investor_identifier,
                    brief.as_of.isoformat(),
                    brief.snapshot_identifier,
                    brief.policy_identifier,
                    json.dumps(replay_identifiers),
                    encoded,
                ),
            )
        return payload

    def history(
        self,
        investor_identifier: str,
        *,
        limit: int = 50,
    ) -> tuple[dict[str, object], ...]:
        if not isinstance(investor_identifier, str) or not investor_identifier.strip():
            raise ValueError("investor_identifier must be a non-empty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM personal_cio_briefs
                WHERE investor_identifier = ?
                ORDER BY as_of DESC, identifier DESC
                LIMIT ?
                """,
                (investor_identifier.strip(), limit),
            ).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                connection.execute(
                    "SELECT COUNT(*) FROM personal_cio_briefs"
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"Personal CIO brief history is unavailable: {error}"
        return True, "Personal CIO brief history is available"

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.path.exists():
                raise FileNotFoundError(self.path)
            encoded = quote(str(self.path.resolve()), safe="/")
            connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


__all__ = ["SQLitePersonalCIOBriefStore"]
