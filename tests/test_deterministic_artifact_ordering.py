from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from cio_pending_transactions import (
    build_pending_transaction_report,
    pending_report_history_directory,
    pending_transaction_report_history,
    write_pending_transaction_report,
)
from operations.artifact_ordering import ordered_json_artifacts
from operations.backup import SQLiteBackupManager


UTC = timezone.utc


def _database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE evidence (value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('governed')")


def test_touching_pending_reports_cannot_reorder_embedded_history(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    construction = {
        "request_identifier": "construction:1",
        "status": "feasible",
        "trades": [],
        "blocks": [],
    }
    first = build_pending_transaction_report(
        construction=construction,
        briefing={"decision_identifier": "decision:1"},
        generated_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
        execution_state="held",
    )
    second = build_pending_transaction_report(
        construction=construction,
        briefing={"decision_identifier": "decision:1"},
        generated_at=datetime(2026, 7, 30, 13, tzinfo=UTC),
        execution_state="completed",
    )
    write_pending_transaction_report(first)
    write_pending_transaction_report(second)
    paths = list(pending_report_history_directory().glob("*.json"))
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        forced = 2_000_000_000 if payload["execution_state"] == "held" else 1
        os.utime(path, (forced, forced))

    assert [item["execution_state"] for item in pending_transaction_report_history()] == [
        "completed",
        "held",
    ]


def test_equal_timestamp_uses_stable_identifier_not_filename_or_mtime(tmp_path) -> None:
    timestamp = "2026-07-30T13:00:00+00:00"
    for filename, identifier in (("z.json", "attempt:a"), ("a.json", "attempt:b")):
        path = tmp_path / filename
        path.write_text(
            json.dumps({"attempted_at": timestamp, "execution_identifier": identifier}),
            encoding="utf-8",
        )
    ranked = ordered_json_artifacts(
        tmp_path.glob("*.json"),
        timestamp_fields=("attempted_at",),
        identifier_fields=("execution_identifier",),
    )
    assert [payload["execution_identifier"] for _, payload in ranked] == [
        "attempt:b",
        "attempt:a",
    ]


def test_backup_selection_and_pruning_use_manifest_time_not_mtime(tmp_path) -> None:
    source = tmp_path / "state.db"
    _database(source)
    clock = [datetime(2026, 7, 1, 12, tzinfo=UTC)]
    manager = SQLiteBackupManager(
        {"state": source},
        tmp_path / "backups",
        retention_days=30,
        clock=lambda: clock[0],
    )
    older = manager.create_backup().archive
    clock[0] += timedelta(days=2)
    newer = manager.create_backup().archive
    os.utime(older, (2_000_000_000, 2_000_000_000))
    os.utime(newer, (1, 1))

    healthy, _, selected = manager.latest_backup_health(
        maximum_age_seconds=3 * 24 * 3600
    )
    assert healthy is True
    assert selected == newer

    pruning = SQLiteBackupManager(
        {"state": source},
        tmp_path / "backups",
        retention_days=1,
        clock=lambda: clock[0],
    )
    assert pruning.prune() == (older,)
    assert newer.exists()


def test_invalid_or_naive_embedded_timestamp_is_not_ranked(tmp_path) -> None:
    (tmp_path / "naive.json").write_text(
        json.dumps({"generated_at": "2026-07-30T12:00:00", "id": "bad"}),
        encoding="utf-8",
    )
    assert ordered_json_artifacts(
        tmp_path.glob("*.json"),
        timestamp_fields=("generated_at",),
        identifier_fields=("id",),
    ) == ()
