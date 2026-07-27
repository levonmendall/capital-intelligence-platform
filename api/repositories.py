"""Read-only repositories used by the production API boundary."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from api.config import ApiSettings


class RepositoryUnavailableError(RuntimeError):
    """A required backing store cannot be read safely."""


class RepositoryConflictError(RuntimeError):
    """The same immutable identifier resolves to conflicting payloads."""


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.exists() or not path.is_file():
        raise RepositoryUnavailableError(f"database is unavailable: {path}")
    encoded = quote(str(path.resolve()), safe="/")
    try:
        connection = sqlite3.connect(
            f"file:{encoded}?mode=ro",
            uri=True,
            timeout=5.0,
        )
    except sqlite3.Error as error:
        raise RepositoryUnavailableError(
            f"database cannot be opened read-only: {path}"
        ) from error
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _decode_object(value: str, *, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise RepositoryUnavailableError(
            f"stored JSON is invalid: {source}"
        ) from error
    if not isinstance(payload, dict):
        raise RepositoryUnavailableError(
            f"stored JSON must be an object: {source}"
        )
    return payload


@dataclass(frozen=True, slots=True)
class ReadinessComponent:
    name: str
    required: bool
    ready: bool
    detail: str


class DailySnapshotRepository:
    """Read canonical daily payloads without rerunning intelligence."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def check(self) -> ReadinessComponent:
        try:
            with _read_only_connection(self.path) as connection:
                connection.execute(
                    "SELECT 1 FROM daily_intelligence_snapshots LIMIT 1"
                ).fetchone()
        except (sqlite3.Error, RepositoryUnavailableError) as error:
            return ReadinessComponent(
                name="daily_snapshots",
                required=True,
                ready=False,
                detail=str(error),
            )
        return ReadinessComponent(
            name="daily_snapshots",
            required=True,
            ready=True,
            detail="append-only snapshot store is readable",
        )

    def latest_payload(self) -> dict[str, Any] | None:
        try:
            with _read_only_connection(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT identifier, payload_json
                    FROM daily_intelligence_snapshots
                    ORDER BY as_of DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "daily snapshot store cannot be queried"
            ) from error
        if row is None:
            return None
        return _decode_object(
            row["payload_json"],
            source=f"snapshot:{row['identifier']}",
        )

    def history(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[dict[str, Any], ...]:
        try:
            with _read_only_connection(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        identifier,
                        as_of,
                        generated_at,
                        score,
                        score_delta,
                        status,
                        environment,
                        risk,
                        committee,
                        portfolio_impact,
                        changed_materially,
                        should_alert,
                        replay_identifiers_json
                    FROM daily_intelligence_snapshots
                    ORDER BY as_of DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "daily snapshot history cannot be queried"
            ) from error
        items: list[dict[str, Any]] = []
        for row in rows:
            replay_ids = json.loads(row["replay_identifiers_json"])
            items.append(
                {
                    "identifier": row["identifier"],
                    "as_of": row["as_of"],
                    "generated_at": row["generated_at"],
                    "score": int(row["score"]),
                    "score_delta": (
                        None
                        if row["score_delta"] is None
                        else int(row["score_delta"])
                    ),
                    "status": row["status"],
                    "environment": row["environment"],
                    "risk": row["risk"],
                    "committee": row["committee"],
                    "portfolio_impact": row["portfolio_impact"],
                    "changed_materially": bool(row["changed_materially"]),
                    "should_alert": bool(row["should_alert"]),
                    "decision_replays": list(replay_ids),
                }
            )
        return tuple(items)

    def count(self) -> int:
        try:
            with _read_only_connection(self.path) as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM daily_intelligence_snapshots"
                ).fetchone()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "daily snapshot store cannot be counted"
            ) from error
        return int(row["count"])

    def find_decision(self, decision_identifier: str) -> dict[str, Any] | None:
        try:
            with _read_only_connection(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT identifier, payload_json
                    FROM daily_intelligence_snapshots
                    ORDER BY as_of DESC
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "daily decisions cannot be queried"
            ) from error
        for row in rows:
            payload = _decode_object(
                row["payload_json"],
                source=f"snapshot:{row['identifier']}",
            )
            sources = payload.get("sources", {})
            if sources.get("decision") == decision_identifier:
                return {
                    "decision_identifier": decision_identifier,
                    "snapshot_identifier": payload.get("identifier"),
                    "as_of": payload.get("as_of"),
                    "decision_card": payload.get("decision_card"),
                    "sources": sources,
                }
        return None

    def replay_identifiers(self) -> tuple[str, ...]:
        try:
            with _read_only_connection(self.path) as connection:
                rows = connection.execute(
                    """
                    SELECT replay_identifiers_json
                    FROM daily_intelligence_snapshots
                    ORDER BY as_of DESC
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "decision replay references cannot be queried"
            ) from error
        identifiers: set[str] = set()
        for row in rows:
            values = json.loads(row["replay_identifiers_json"])
            if not isinstance(values, list):
                raise RepositoryUnavailableError(
                    "stored replay identifiers must be a JSON array"
                )
            identifiers.update(str(value) for value in values)
        return tuple(sorted(identifiers))


class PortfolioRepository:
    """Read the append-only canonical portfolio-state source."""

    _TABLE = "canonical_portfolio_events"

    def __init__(self, path: Path) -> None:
        self.path = path

    def check(self) -> ReadinessComponent:
        try:
            with _read_only_connection(self.path) as connection:
                connection.execute(f"SELECT 1 FROM {self._TABLE} LIMIT 1").fetchone()
        except (sqlite3.Error, RepositoryUnavailableError) as error:
            return ReadinessComponent(
                name="canonical_portfolios",
                required=True,
                ready=False,
                detail=str(error),
            )
        return ReadinessComponent(
            name="canonical_portfolios",
            required=True,
            ready=True,
            detail="append-only canonical portfolio state is readable",
        )

    @staticmethod
    def _decode(row: sqlite3.Row):
        from portfolio.state import snapshot_from_dict

        return snapshot_from_dict(_decode_object(row["payload_json"], source="canonical-portfolio"))

    def list(self) -> tuple[dict[str, Any], ...]:
        from portfolio.state import snapshot_summary

        try:
            with _read_only_connection(self.path) as connection:
                rows = connection.execute(f"""
                    SELECT events.payload_json
                    FROM {self._TABLE} AS events
                    INNER JOIN (
                        SELECT portfolio_code, MAX(sequence) AS sequence
                        FROM {self._TABLE}
                        GROUP BY portfolio_code
                    ) AS latest
                    ON events.portfolio_code = latest.portfolio_code
                    AND events.sequence = latest.sequence
                    ORDER BY events.portfolio_code
                """).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError("canonical portfolio state cannot be queried") from error
        return tuple(snapshot_summary(self._decode(row)) for row in rows)

    def get(self, code: str) -> dict[str, Any] | None:
        from portfolio.state import snapshot_details

        normalized = code.strip().upper()
        try:
            with _read_only_connection(self.path) as connection:
                latest = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} WHERE portfolio_code = ? ORDER BY sequence DESC LIMIT 1",
                    (normalized,),
                ).fetchone()
                if latest is None:
                    return None
                history = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} WHERE portfolio_code = ? ORDER BY sequence DESC LIMIT 250",
                    (normalized,),
                ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError("canonical portfolio details cannot be queried") from error
        return snapshot_details(
            self._decode(latest),
            history=tuple(self._decode(row) for row in history),
        )


class ReplayRepository:
    """Read immutable replay JSON artifacts from a configured directory."""

    def __init__(self, directory: Path | None) -> None:
        self.directory = directory

    def check(self) -> ReadinessComponent:
        if self.directory is None:
            return ReadinessComponent(
                name="decision_replays",
                required=False,
                ready=True,
                detail="replay artifact directory is not configured",
            )
        if not self.directory.exists():
            return ReadinessComponent(
                name="decision_replays",
                required=False,
                ready=True,
                detail="replay artifact directory has not been created",
            )
        if not self.directory.is_dir() or not os.access(self.directory, os.R_OK):
            return ReadinessComponent(
                name="decision_replays",
                required=False,
                ready=False,
                detail="replay artifact directory is not readable",
            )
        try:
            self._index()
        except (RepositoryUnavailableError, RepositoryConflictError) as error:
            return ReadinessComponent(
                name="decision_replays",
                required=False,
                ready=False,
                detail=str(error),
            )
        return ReadinessComponent(
            name="decision_replays",
            required=False,
            ready=True,
            detail="replay artifacts are readable",
        )

    def list_payloads(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._index().values())

    def get(self, identifier: str) -> dict[str, Any] | None:
        return self._index().get(identifier)

    def _index(self) -> dict[str, dict[str, Any]]:
        if self.directory is None or not self.directory.exists():
            return {}
        if not self.directory.is_dir():
            raise RepositoryUnavailableError(
                "replay artifact path must be a directory"
            )
        payloads: dict[str, dict[str, Any]] = {}
        canonical: dict[str, str] = {}
        for path in sorted(self.directory.glob("*.json")):
            try:
                value = path.read_text(encoding="utf-8")
            except OSError as error:
                raise RepositoryUnavailableError(
                    f"replay artifact cannot be read: {path.name}"
                ) from error
            payload = _decode_object(value, source=f"replay:{path.name}")
            identifier = payload.get("identifier")
            if not isinstance(identifier, str) or not identifier.strip():
                raise RepositoryUnavailableError(
                    f"replay artifact has no identifier: {path.name}"
                )
            normalized = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            )
            if identifier in canonical and canonical[identifier] != normalized:
                raise RepositoryConflictError(
                    f"conflicting replay identifier: {identifier}"
                )
            canonical[identifier] = normalized
            payloads[identifier] = payload
        return payloads


class JournalRepository:
    """Read canonical CIO events from the append-only journal."""

    _TABLE = "cio_journal_events"

    def __init__(self, path: Path, *, required: bool) -> None:
        self.path = path
        self.required = required

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (JournalRepository._TABLE,),
        ).fetchone()
        return row is not None

    def check(self) -> ReadinessComponent:
        if not self.path.exists() and not self.required:
            return ReadinessComponent(
                name="institutional_journal",
                required=False,
                ready=True,
                detail="CIO journal is optional and has not been created",
            )
        try:
            with _read_only_connection(self.path) as connection:
                has_table = self._has_table(connection)
        except (sqlite3.Error, RepositoryUnavailableError) as error:
            return ReadinessComponent(
                name="institutional_journal",
                required=self.required,
                ready=False,
                detail=str(error),
            )
        if not has_table:
            return ReadinessComponent(
                name="institutional_journal",
                required=self.required,
                ready=not self.required,
                detail=(
                    "canonical CIO journal table has not been created"
                    if not self.required
                    else "canonical CIO journal table is required but missing"
                ),
            )
        return ReadinessComponent(
            name="institutional_journal",
            required=self.required,
            ready=True,
            detail="append-only canonical CIO journal is readable",
        )

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        payload = _decode_object(
            str(row["payload_json"]),
            source=f"cio-journal:{row['event_identifier']}",
        )
        return {
            **payload,
            "journal": {
                "sequence": int(row["sequence"]),
                "event_identifier": str(row["event_identifier"]),
                "aggregate_identifier": str(row["aggregate_identifier"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "recorded_at": str(row["recorded_at"]),
                "schema_version": str(row["schema_version"]),
                "content_hash": str(row["content_hash"]),
            },
        }

    def latest_payload(
        self,
        event_type: str,
        *,
        aggregate_identifier: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["event_type = ?"]
        parameters: list[object] = [event_type]
        if aggregate_identifier is not None:
            clauses.append("aggregate_identifier = ?")
            parameters.append(aggregate_identifier)
        try:
            with _read_only_connection(self.path) as connection:
                if not self._has_table(connection):
                    return None
                row = connection.execute(
                    f"""
                    SELECT * FROM {self._TABLE}
                    WHERE {' AND '.join(clauses)}
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    tuple(parameters),
                ).fetchone()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "canonical CIO journal cannot be queried"
            ) from error
        return None if row is None else self._payload(row)

    def history(
        self,
        event_type: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        try:
            with _read_only_connection(self.path) as connection:
                if not self._has_table(connection):
                    return ()
                rows = connection.execute(
                    f"""
                    SELECT * FROM {self._TABLE}
                    WHERE event_type = ?
                    ORDER BY sequence DESC
                    LIMIT ? OFFSET ?
                    """,
                    (event_type, limit, offset),
                ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "canonical CIO journal history cannot be queried"
            ) from error
        return tuple(self._payload(row) for row in rows)

    def latest_per_aggregate(
        self,
        event_type: str,
        *,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        try:
            with _read_only_connection(self.path) as connection:
                if not self._has_table(connection):
                    return ()
                rows = connection.execute(
                    f"""
                    SELECT event.*
                    FROM {self._TABLE} AS event
                    JOIN (
                        SELECT aggregate_identifier, MAX(sequence) AS sequence
                        FROM {self._TABLE}
                        WHERE event_type = ?
                        GROUP BY aggregate_identifier
                    ) AS latest
                    ON event.sequence = latest.sequence
                    ORDER BY event.sequence DESC
                    LIMIT ?
                    """,
                    (event_type, limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "canonical CIO journal aggregates cannot be queried"
            ) from error
        return tuple(self._payload(row) for row in rows)

    def count(self, event_type: str) -> int:
        try:
            with _read_only_connection(self.path) as connection:
                if not self._has_table(connection):
                    return 0
                row = connection.execute(
                    f"SELECT COUNT(*) AS count FROM {self._TABLE} WHERE event_type = ?",
                    (event_type,),
                ).fetchone()
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "canonical CIO journal count cannot be queried"
            ) from error
        return int(row["count"])


@dataclass(frozen=True, slots=True)
class ApiResources:
    snapshots: DailySnapshotRepository
    portfolios: PortfolioRepository
    replays: ReplayRepository
    journal: JournalRepository
    live_provider_configured: bool
    require_live_provider: bool

    def readiness(self) -> tuple[ReadinessComponent, ...]:
        provider_ready = (
            self.live_provider_configured or not self.require_live_provider
        )
        provider_detail = (
            "live provider credentials are configured"
            if self.live_provider_configured
            else "live provider credentials are not required"
            if not self.require_live_provider
            else "FRED_API_KEY is required but missing"
        )
        return (
            self.snapshots.check(),
            self.portfolios.check(),
            self.replays.check(),
            self.journal.check(),
            ReadinessComponent(
                name="live_provider",
                required=self.require_live_provider,
                ready=provider_ready,
                detail=provider_detail,
            ),
        )


def build_resources(settings: ApiSettings) -> ApiResources:
    return ApiResources(
        snapshots=DailySnapshotRepository(settings.snapshot_database),
        portfolios=PortfolioRepository(settings.portfolio_database),
        replays=ReplayRepository(settings.replay_directory),
        journal=JournalRepository(
            settings.journal_database,
            required=settings.require_journal,
        ),
        live_provider_configured=bool(os.getenv("FRED_API_KEY", "").strip()),
        require_live_provider=settings.require_live_provider,
    )


__all__ = [
    "ApiResources",
    "DailySnapshotRepository",
    "JournalRepository",
    "PortfolioRepository",
    "ReadinessComponent",
    "ReplayRepository",
    "RepositoryConflictError",
    "RepositoryUnavailableError",
    "build_resources",
]
