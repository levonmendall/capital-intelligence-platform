"""Deployment validation for the complete fenced daily workflow."""

from __future__ import annotations

import json
from pathlib import Path

from operations import CANONICAL_DAILY_STAGE_ORDER, DailyOperationEventType
from operations.daily_leases import LeasedSQLiteCanonicalDailyOperationsStore
from operations.stage_bindings import load_stage_bindings, validate_stage_bindings
from run_daily_operations import _load_plan, _validate_plan_runtime, main


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "deploy" / "canonical-daily-operations.json"
VALIDATION_BINDINGS = (
    ROOT / "deploy" / "canonical-daily-stage-bindings.validation.json"
)


def test_shipped_plan_and_validation_bindings_cover_exact_stage_order(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS",
        str(VALIDATION_BINDINGS),
    )
    plan = _load_plan(PLAN)
    report = _validate_plan_runtime(plan)
    bindings = load_stage_bindings(VALIDATION_BINDINGS)

    assert plan["schema_version"] == "canonical-daily-operations.v2"
    assert plan["lease_required"] is True
    assert tuple(plan["stages"]) == tuple(
        stage.value for stage in CANONICAL_DAILY_STAGE_ORDER
    )
    assert tuple(bindings) == CANONICAL_DAILY_STAGE_ORDER
    assert report["status"] == "valid"
    assert report["stage_count"] == 12
    assert report["lease_required"] is True
    assert report["binding_reports"][0]["status"] == "valid"
    assert validate_stage_bindings(VALIDATION_BINDINGS)["stages"] == [
        stage.value for stage in CANONICAL_DAILY_STAGE_ORDER
    ]


def test_validation_plan_completes_all_stages_through_subprocess_adapters(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS",
        str(VALIDATION_BINDINGS),
    )
    database = tmp_path / "daily.db"

    exit_code = main(
        (
            "--plan",
            str(PLAN),
            "--database",
            str(database),
            "--worker-identifier",
            "pytest-container-worker",
            "--lease-seconds",
            "30",
            "--lease-heartbeat-seconds",
            "1",
            "--operation-id",
            "canonical-daily:validation:2026-07-27",
            "--idempotency-key",
            "canonical-daily:validation:2026-07-27:process-v1",
            "--scheduled-for",
            "2026-07-27T00:00:00+00:00",
            "--decision-timestamp",
            "2026-07-27T01:00:00+00:00",
            "--knowledge-cutoff",
            "2026-07-27T01:00:00+00:00",
            "--started-at",
            "2026-07-27T02:00:00+00:00",
            "--operation-timezone",
            "UTC",
            "--operation-hour",
            "0",
            "--process-version",
            "process-v1",
            "--code-version",
            "commit:validation",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["completed_stages"] == [
        stage.value for stage in CANONICAL_DAILY_STAGE_ORDER
    ]
    assert payload["worker_identifier"] == "pytest-container-worker"
    assert payload["output_identifiers"][0].startswith(
        "stage-publication:canonical-daily:validation:2026-07-27:"
        "slo_assessment:"
    )
    store = LeasedSQLiteCanonicalDailyOperationsStore(
        database,
        worker_identifier="read-only-validation-worker",
    )
    events = store.events("canonical-daily:validation:2026-07-27")
    completions = tuple(
        event
        for event in events
        if event["event_type"] == DailyOperationEventType.STAGE_COMPLETED.value
    )
    assert len(completions) == 12
    assert tuple(event["stage"] for event in completions) == tuple(
        stage.value for stage in CANONICAL_DAILY_STAGE_ORDER
    )
    assert all(
        event["payload"]["lease"]["worker_identifier"]
        == "pytest-container-worker"
        for event in completions
    )
    assert store.verify_integrity()


def test_validate_plan_command_performs_startup_checks_without_running_stages(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS",
        str(VALIDATION_BINDINGS),
    )

    exit_code = main(("--plan", str(PLAN), "--validate-plan"))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "valid"
    assert payload["stage_count"] == 12
    assert payload["lease_required"] is True
    assert payload["real_money_authorized"] is False
