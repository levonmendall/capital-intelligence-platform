"""Durable fenced leases for exact paper-construction execution."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


class PaperExecutionLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PaperExecutionLeaseGrant:
    construction_sha256: str
    owner_identifier: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime


class SQLitePaperExecutionLeaseStore:
    def __init__(self, path: str | Path, *, clock=None) -> None:
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_execution_leases (
                    construction_sha256 TEXT PRIMARY KEY,
                    owner_identifier TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("paper execution lease clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def acquire(
        self,
        construction_sha256: str,
        *,
        owner_identifier: str,
        lease_seconds: int,
    ) -> PaperExecutionLeaseGrant | None:
        if lease_seconds < 15:
            raise ValueError("paper execution lease must be at least 15 seconds")
        now = self._now()
        expires = now + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM paper_execution_leases WHERE construction_sha256 = ?",
                (construction_sha256,),
            ).fetchone()
            if row is not None:
                prior_expiry = datetime.fromisoformat(str(row["expires_at"]))
                if prior_expiry > now and str(row["owner_identifier"]) != owner_identifier:
                    connection.rollback()
                    return None
                token = int(row["fencing_token"]) + 1
            else:
                token = 1
            connection.execute(
                """
                INSERT INTO paper_execution_leases (
                    construction_sha256, owner_identifier, fencing_token,
                    acquired_at, heartbeat_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(construction_sha256) DO UPDATE SET
                    owner_identifier=excluded.owner_identifier,
                    fencing_token=excluded.fencing_token,
                    acquired_at=excluded.acquired_at,
                    heartbeat_at=excluded.heartbeat_at,
                    expires_at=excluded.expires_at
                """,
                (
                    construction_sha256,
                    owner_identifier,
                    token,
                    now.isoformat(),
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
            connection.commit()
        return PaperExecutionLeaseGrant(
            construction_sha256=construction_sha256,
            owner_identifier=owner_identifier,
            fencing_token=token,
            acquired_at=now,
            expires_at=expires,
        )

    def renew(
        self,
        grant: PaperExecutionLeaseGrant,
        *,
        lease_seconds: int,
    ) -> PaperExecutionLeaseGrant:
        now = self._now()
        expires = now + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE paper_execution_leases
                SET heartbeat_at = ?, expires_at = ?
                WHERE construction_sha256 = ? AND owner_identifier = ?
                  AND fencing_token = ? AND expires_at >= ?
                """,
                (
                    now.isoformat(),
                    expires.isoformat(),
                    grant.construction_sha256,
                    grant.owner_identifier,
                    grant.fencing_token,
                    now.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise PaperExecutionLeaseLost(
                    "paper execution fencing token is stale or expired"
                )
            connection.commit()
        return PaperExecutionLeaseGrant(
            construction_sha256=grant.construction_sha256,
            owner_identifier=grant.owner_identifier,
            fencing_token=grant.fencing_token,
            acquired_at=grant.acquired_at,
            expires_at=expires,
        )

    def release(self, grant: PaperExecutionLeaseGrant) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM paper_execution_leases WHERE construction_sha256 = ? "
                "AND owner_identifier = ? AND fencing_token = ?",
                (
                    grant.construction_sha256,
                    grant.owner_identifier,
                    grant.fencing_token,
                ),
            )


__all__ = [
    "PaperExecutionLeaseGrant",
    "PaperExecutionLeaseLost",
    "SQLitePaperExecutionLeaseStore",
]
