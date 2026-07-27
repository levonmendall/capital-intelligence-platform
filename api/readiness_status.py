"""Read persisted operational and paper-test readiness as separate statuses."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from api.repositories import RepositoryUnavailableError, _read_only_connection


class ReadinessStatusRepository:
    """Read canonical readiness evidence without treating process health as proof."""

    _EVIDENCE_TABLE = "product_readiness_evidence_events"
    _REPORT_TABLE = "product_test_readiness_reports"

    def __init__(
        self,
        *,
        readiness_evidence_path: Path,
        product_test_readiness_path: Path,
    ) -> None:
        self.readiness_evidence_path = readiness_evidence_path
        self.product_test_readiness_path = product_test_readiness_path

    @staticmethod
    def _has_table(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            is not None
        )

    def latest_operational(self) -> dict[str, Any]:
        if not self.readiness_evidence_path.exists():
            return {
                "state": "unavailable",
                "ready": False,
                "detail": "operational readiness evidence database is unavailable",
                "evidence": None,
            }
        try:
            with _read_only_connection(self.readiness_evidence_path) as connection:
                if not self._has_table(connection, self._EVIDENCE_TABLE):
                    return {
                        "state": "unavailable",
                        "ready": False,
                        "detail": "operational readiness evidence table is unavailable",
                        "evidence": None,
                    }
                row = connection.execute(
                    f"SELECT event_identifier, payload_json FROM {self._EVIDENCE_TABLE} "
                    "WHERE event_type='operational_snapshot' "
                    "ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
        except (sqlite3.Error, RepositoryUnavailableError) as error:
            return {
                "state": "unavailable",
                "ready": False,
                "detail": str(error),
                "evidence": None,
            }
        if row is None:
            return {
                "state": "unavailable",
                "ready": False,
                "detail": "no operational readiness snapshot has been published",
                "evidence": None,
            }
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as error:
            raise RepositoryUnavailableError(
                "operational readiness snapshot contains invalid JSON"
            ) from error
        blockers = {
            "unresolved_critical_incidents": int(
                payload["unresolved_critical_incidents"]
            ),
            "data_integrity_failures": int(payload["data_integrity_failures"]),
            "reconciliation_failures": int(payload["reconciliation_failures"]),
        }
        ready = all(value == 0 for value in blockers.values())
        return {
            "state": "ready" if ready else "blocked",
            "ready": ready,
            "detail": (
                "latest persisted operational snapshot has no critical blockers"
                if ready
                else "latest persisted operational snapshot contains blockers"
            ),
            "evidence_identifier": str(row["event_identifier"]),
            "evidence": payload,
            "blockers": blockers,
        }

    def latest_paper_test(self) -> dict[str, Any]:
        if not self.product_test_readiness_path.exists():
            return {
                "state": "development_in_progress",
                "ready": False,
                "detail": "paper-test readiness report database is unavailable",
                "evidence": None,
            }
        try:
            with _read_only_connection(
                self.product_test_readiness_path
            ) as connection:
                if not self._has_table(connection, self._REPORT_TABLE):
                    return {
                        "state": "development_in_progress",
                        "ready": False,
                        "detail": "paper-test readiness report table is unavailable",
                        "evidence": None,
                    }
                row = connection.execute(
                    f"SELECT identifier, payload_json FROM {self._REPORT_TABLE} "
                    "ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
        except (sqlite3.Error, RepositoryUnavailableError) as error:
            return {
                "state": "development_in_progress",
                "ready": False,
                "detail": str(error),
                "evidence": None,
            }
        if row is None:
            return {
                "state": "development_in_progress",
                "ready": False,
                "detail": "no paper-test readiness report has been published",
                "evidence": None,
            }
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as error:
            raise RepositoryUnavailableError(
                "paper-test readiness report contains invalid JSON"
            ) from error
        state = str(payload.get("state") or "development_in_progress")
        ready = state == "ready_for_controlled_paper_test"
        return {
            "state": state,
            "ready": ready,
            "detail": (
                "immutable baseline is approved for controlled paper testing"
                if ready
                else "immutable baseline is not approved for controlled paper testing"
            ),
            "evidence_identifier": str(row["identifier"]),
            "evidence": payload,
            "real_money_authorized": False,
            "performance_claims_permitted": False,
        }


__all__ = ["ReadinessStatusRepository"]
