"""Read the certified decision Environment and later observations safely."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from api.repositories import (
    ReadinessComponent,
    RepositoryUnavailableError,
    _decode_object,
    _read_only_connection,
)


class CanonicalEnvironmentRepository:
    """Read the append-only canonical Environment authority without mutation."""

    _TABLE = "canonical_environment_events"

    def __init__(self, path: Path, *, required: bool) -> None:
        self.path = path
        self.required = required

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (CanonicalEnvironmentRepository._TABLE,),
        ).fetchone()
        return row is not None

    def check(self) -> ReadinessComponent:
        if not self.path.exists() and not self.required:
            return ReadinessComponent(
                name="canonical_environment",
                required=False,
                ready=True,
                detail="canonical Environment authority is optional and not created",
            )
        try:
            with _read_only_connection(self.path) as connection:
                has_table = self._has_table(connection)
                snapshot = (
                    connection.execute(
                        f"SELECT 1 FROM {self._TABLE} "
                        "WHERE event_type='decision_snapshot' LIMIT 1"
                    ).fetchone()
                    if has_table
                    else None
                )
        except (sqlite3.Error, RepositoryUnavailableError) as error:
            return ReadinessComponent(
                name="canonical_environment",
                required=self.required,
                ready=False,
                detail=str(error),
            )
        if not has_table or snapshot is None:
            return ReadinessComponent(
                name="canonical_environment",
                required=self.required,
                ready=not self.required,
                detail=(
                    "certified decision Environment snapshot is unavailable"
                    if self.required
                    else "canonical Environment has no published decision snapshot"
                ),
            )
        return ReadinessComponent(
            name="canonical_environment",
            required=self.required,
            ready=True,
            detail="certified decision Environment authority is readable",
        )

    def latest_view(self) -> dict[str, Any] | None:
        if not self.path.exists() and not self.required:
            return None
        try:
            with _read_only_connection(self.path) as connection:
                if not self._has_table(connection):
                    return None
                row = connection.execute(
                    f"SELECT identifier, payload_json FROM {self._TABLE} "
                    "WHERE event_type='decision_snapshot' "
                    "ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                snapshot = _decode_object(
                    str(row["payload_json"]),
                    source=f"environment:{row['identifier']}",
                )
                observations = connection.execute(
                    f"SELECT identifier, payload_json FROM {self._TABLE} "
                    "WHERE event_type='subsequent_observation' "
                    "AND snapshot_identifier=? ORDER BY sequence",
                    (str(row["identifier"]),),
                ).fetchall()
        except RepositoryUnavailableError:
            if not self.required:
                return None
            raise
        except sqlite3.Error as error:
            raise RepositoryUnavailableError(
                "canonical Environment authority cannot be queried"
            ) from error
        later = [
            _decode_object(
                str(item["payload_json"]),
                source=f"environment-observation:{item['identifier']}",
            )
            for item in observations
        ]
        return {
            "snapshot_identifier": snapshot["identifier"],
            "decision_identifier": snapshot["decision_identifier"],
            "context_identifier": snapshot["context_identifier"],
            "screening_publication_identifier": snapshot[
                "screening_publication_identifier"
            ],
            "as_of": snapshot["as_of"],
            "knowledge_cutoff": snapshot["knowledge_cutoff"],
            "published_at": snapshot["published_at"],
            "environment": snapshot["environment"],
            "evidence_identifiers": snapshot["evidence_identifiers"],
            "source_versions": dict(snapshot.get("source_versions", ())),
            "model_versions": dict(snapshot.get("model_versions", ())),
            "code_version": snapshot["code_version"],
            "process_version": snapshot["process_version"],
            "decision_time_certified": True,
            "subsequent_observations": later,
            "subsequent_observation_count": len(later),
            "schema_version": "canonical-environment-view.v1",
        }


__all__ = ["CanonicalEnvironmentRepository"]
