"""Append-only SQLite persistence for temporal investment graph snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from intelligence.investment_graph import InvestmentEntity, InvestmentRelationship


class InvestmentGraphIntegrityError(RuntimeError):
    pass


class SQLiteInvestmentGraphStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS investment_graph_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS investment_graph_no_update
                BEFORE UPDATE ON investment_graph_events
                BEGIN SELECT RAISE(ABORT, 'investment graph is append only'); END;
                CREATE TRIGGER IF NOT EXISTS investment_graph_no_delete
                BEFORE DELETE ON investment_graph_events
                BEGIN SELECT RAISE(ABORT, 'investment graph is append only'); END;
                """
            )

    @staticmethod
    def _hash(previous_hash: str | None, payload_json: str) -> str:
        return hashlib.sha256(((previous_hash or "") + "\n" + payload_json).encode()).hexdigest()

    def _append(self, identifier: str, event_type: str, payload: dict[str, object]) -> str:
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT content_hash FROM investment_graph_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(prior[0]) if prior is not None else None
            content_hash = self._hash(previous_hash, payload_json)
            existing = connection.execute(
                "SELECT payload_json FROM investment_graph_events WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) == payload_json:
                    return content_hash
                raise InvestmentGraphIntegrityError("conflicting graph event identifier")
            connection.execute(
                "INSERT INTO investment_graph_events(event_identifier,event_type,payload_json,previous_hash,content_hash) VALUES(?,?,?,?,?)",
                (identifier, event_type, payload_json, previous_hash, content_hash),
            )
        return content_hash

    def append_entity(self, entity: InvestmentEntity) -> str:
        return self._append(
            entity.identifier,
            "entity",
            {
                "identifier": entity.identifier,
                "entity_type": entity.entity_type.value,
                "name": entity.name,
                "effective_at": entity.effective_at.isoformat(),
                "source_identifiers": list(entity.source_identifiers),
            },
        )

    def append_relationship(self, relationship: InvestmentRelationship) -> str:
        return self._append(relationship.identifier, "relationship", relationship.to_dict())

    def verify(self) -> None:
        previous_hash: str | None = None
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json,previous_hash,content_hash FROM investment_graph_events ORDER BY sequence"
            ).fetchall()
        for row in rows:
            if row["previous_hash"] != previous_hash:
                raise InvestmentGraphIntegrityError("graph previous hash mismatch")
            expected = self._hash(previous_hash, str(row["payload_json"]))
            if row["content_hash"] != expected:
                raise InvestmentGraphIntegrityError("graph content hash mismatch")
            previous_hash = str(row["content_hash"])


__all__ = ["InvestmentGraphIntegrityError", "SQLiteInvestmentGraphStore"]
