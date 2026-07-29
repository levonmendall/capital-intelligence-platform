from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from production_smoke_test import (
    capture_pre_restart_snapshot,
    create_encrypted_backup_now,
    evaluate_runtime_smoke_test,
    load_pre_restart_snapshot,
)


def _database(path: Path, rows: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS records (identifier INTEGER PRIMARY KEY, value TEXT)"
        )
        for identifier in range(rows):
            connection.execute(
                "INSERT OR REPLACE INTO records(identifier, value) VALUES (?, ?)",
                (identifier, f"value-{identifier}"),
            )


def _runtime_files(root: Path, now: datetime) -> None:
    (root / "cio_reports").mkdir(parents=True, exist_ok=True)
    (root / "worker-heartbeat.json").write_text(
        json.dumps(
            {
                "status": "healthy",
                "observed_at": now.isoformat(),
                "cycle_key": "2026-07-29",
                "detail": "public_collection=available; cio_cycle=completed; paper_execution=idle",
                "pid": 12,
            }
        ),
        encoding="utf-8",
    )
    (root / "public-live-information-runtime-state.json").write_text(
        json.dumps(
            {
                "state": "available",
                "completed_at": now.isoformat(),
                "required_sources_ready": True,
                "source_count": 4,
                "failed_source_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (root / "cio_reports" / "pending_transactions_latest.json").write_text(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "portfolio_code": "COMPOUNDING",
                "report_state": "no_transaction_recommended",
                "execution_state": "idle",
                "decision_identifier": "decision-1",
                "transaction_count": 0,
                "summary": "The CIO construction currently recommends no portfolio transaction.",
                "paper_only": True,
                "real_money_authorized": False,
            }
        ),
        encoding="utf-8",
    )


def _providers():
    return {
        "alpaca_iex": {
            "status": "connected",
            "account_status": "ACTIVE",
            "market_open": True,
            "quote_count": 15,
            "expected_quote_count": 15,
        },
        "fred": {
            "status": "connected",
            "series": "DGS10",
            "observation_date": "2026-07-29",
        },
    }


def test_capture_then_post_restart_verification_passes(tmp_path: Path) -> None:
    now = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
    environment = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    _database(tmp_path / "canonical_portfolio.db", rows=2)
    _database(tmp_path / "institutional_journal.db", rows=3)
    _runtime_files(tmp_path, now)

    capture_pre_restart_snapshot(
        environ=environment,
        now=now,
        process_marker="before-restart",
    )
    _database(tmp_path / "canonical_portfolio.db", rows=3)
    _database(tmp_path / "institutional_journal.db", rows=4)

    result = evaluate_runtime_smoke_test(
        environ=environment,
        now=now,
        process_marker="after-restart",
        provider_probe=_providers,
        backup_probe=lambda: {
            "status": "healthy",
            "detail": "latest encrypted backup is healthy",
            "archive": "canonical-backup.enc",
        },
    )

    assert result["overall_status"] == "PASS"
    assert all(result["checks"].values())
    assert result["real_money_authorized"] is False
    assert load_pre_restart_snapshot(environment) is not None


def test_verification_requires_an_observed_restart(tmp_path: Path) -> None:
    now = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
    environment = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    _database(tmp_path / "canonical_portfolio.db")
    _database(tmp_path / "institutional_journal.db")
    _runtime_files(tmp_path, now)
    capture_pre_restart_snapshot(
        environ=environment,
        now=now,
        process_marker="same-process",
    )

    result = evaluate_runtime_smoke_test(
        environ=environment,
        now=now,
        process_marker="same-process",
        provider_probe=_providers,
        backup_probe=lambda: {"status": "healthy", "archive": "backup.enc"},
    )

    assert result["checks"]["persistent_state_survived_restart"] is False
    assert "restart has not been observed" in result["persistence"]["failures"][0]


def test_verification_detects_lost_database_rows(tmp_path: Path) -> None:
    now = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
    environment = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    _database(tmp_path / "canonical_portfolio.db", rows=3)
    _database(tmp_path / "institutional_journal.db", rows=3)
    _runtime_files(tmp_path, now)
    capture_pre_restart_snapshot(
        environ=environment,
        now=now,
        process_marker="before",
    )
    with sqlite3.connect(tmp_path / "canonical_portfolio.db") as connection:
        connection.execute("DELETE FROM records WHERE identifier > 0")

    result = evaluate_runtime_smoke_test(
        environ=environment,
        now=now,
        process_marker="after",
        provider_probe=_providers,
        backup_probe=lambda: {"status": "healthy", "archive": "backup.enc"},
    )

    assert result["checks"]["persistent_state_survived_restart"] is False
    assert any("decreased" in item for item in result["persistence"]["failures"])


def test_explicit_backup_action_returns_sanitized_result() -> None:
    manager = SimpleNamespace(
        create_backup=lambda: SimpleNamespace(
            archive=Path("/private/path/backup.enc"),
            encrypted=True,
            manifest={"files": [{"logical_name": "portfolio"}], "schema_version": "v1"},
        )
    )

    result = create_encrypted_backup_now(manager_factory=lambda: manager)

    assert result == {
        "status": "completed",
        "archive": "backup.enc",
        "encrypted": True,
        "database_count": 1,
        "schema_version": "v1",
        "real_money_authorized": False,
    }


def test_render_wrapper_gates_smoke_dialog_to_administrators() -> None:
    source = Path("render_app.py").read_text(encoding="utf-8")

    assert "getattr(principal, \"is_administrator\", False)" in source
    assert "production_smoke_test_open" in source
    assert "render_production_smoke_test(principal)" in source
