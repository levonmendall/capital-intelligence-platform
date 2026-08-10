"""Append-only persistence for read-only whole-portfolio risk synthesis."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from intelligence.portfolio_risk_synthesis import PortfolioRiskSynthesis


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


class SQLitePortfolioRiskSynthesisStore:
    def __init__(self, path: str | Path = "database/portfolio-risk-synthesis.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_risk_synthesis (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append(self, report: PortfolioRiskSynthesis) -> str:
        if not isinstance(report, PortfolioRiskSynthesis):
            raise TypeError("report must be PortfolioRiskSynthesis")
        payload_json = _canonical(report.to_dict())
        content_hash = _hash(payload_json)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM portfolio_risk_synthesis WHERE identifier = ?",
                (report.identifier,),
            ).fetchone()
            if row is not None:
                if str(row["content_hash"]) != content_hash:
                    raise ValueError("risk synthesis identifier already exists with different content")
                return content_hash
            connection.execute(
                "INSERT INTO portfolio_risk_synthesis(identifier, as_of, payload_json, content_hash, recorded_at) VALUES (?, ?, ?, ?, ?)",
                (
                    report.identifier,
                    report.as_of.isoformat(),
                    payload_json,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return content_hash

    def latest(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM portfolio_risk_synthesis ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return None if row is None else json.loads(str(row["payload_json"]))


__all__ = ["SQLitePortfolioRiskSynthesisStore"]
