from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from operations.paper_experiment import (
    REQUIRED_LAUNCH_GATES,
    PaperExperimentObservation,
    PaperExperimentState,
    SQLitePaperExperimentStore,
    evaluate_paper_experiment,
    load_paper_experiment_protocol,
    register_paper_experiment,
)
from capital_intelligence_cli import main as cli_main
import json


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "config" / "paper_experiment_protocol.v1.json"
NOW = datetime(2026, 8, 3, 15, tzinfo=timezone.utc)
SHA = "a" * 40


def _registration(protocol):
    return register_paper_experiment(
        protocol,
        registered_at=NOW,
        start_date=NOW.date(),
        code_version=SHA,
        deployed_git_sha=SHA,
        launch_gates={gate: True for gate in REQUIRED_LAUNCH_GATES},
    )


def _observation(registration, protocol, index, *, missing=False, reconciled=True, benchmark=True):
    day = registration.start_date + timedelta(days=index)
    return PaperExperimentObservation(
        identifier=f"observation:{index}",
        registration_identifier=registration.identifier,
        protocol_fingerprint=protocol.fingerprint,
        code_version=registration.code_version,
        operation_date=day,
        recorded_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=20),
        ending_nav=250_000.0 + index * 100,
        benchmark_nav=250_000.0 + index * 80,
        transaction_cost=4.0,
        turnover=0.01,
        missing_data=missing,
        reconciliation_passed=reconciled,
        benchmark_reconstructable=benchmark,
        source_identifiers=(f"operation:{index}", f"portfolio:{index}"),
    )


def test_protocol_freezes_one_250k_portfolio_universe_costs_benchmark_and_rules() -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    assert protocol.portfolio_code == "COMPOUNDING"
    assert protocol.starting_capital == 250_000.0
    assert len(protocol.universe_identifiers) == 15
    assert protocol.minimum_calendar_days == 42
    assert protocol.minimum_operating_cycles == 30
    assert protocol.maximum_missing_cycles == 2
    assert len(protocol.required_failure_scenarios) == 11
    payload = protocol.to_dict()
    assert payload["automatic_threshold_change_permitted"] is False
    assert payload["performance_claims_permitted"] is False
    assert payload["real_money_authorized"] is False


def test_launch_requires_every_pr_gate_browser_benchmark_and_exact_deployed_sha() -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    gates = {gate: True for gate in REQUIRED_LAUNCH_GATES}
    gates["pr8_real_browser_gate"] = False
    with pytest.raises(ValueError, match="pr8_real_browser_gate"):
        register_paper_experiment(
            protocol, registered_at=NOW, start_date=NOW.date(), code_version=SHA,
            deployed_git_sha=SHA, launch_gates=gates,
        )
    with pytest.raises(ValueError, match="equal the exact deployed"):
        register_paper_experiment(
            protocol, registered_at=NOW, start_date=NOW.date(), code_version=SHA,
            deployed_git_sha="b" * 40,
            launch_gates={gate: True for gate in REQUIRED_LAUNCH_GATES},
        )


def test_multi_week_complete_state_still_requires_human_review() -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    registration = _registration(protocol)
    observations = tuple(_observation(registration, protocol, index) for index in range(30))
    report = evaluate_paper_experiment(
        protocol, registration, observations,
        evaluated_at=NOW + timedelta(days=41),
    )
    assert report.state is PaperExperimentState.COMPLETE_AWAITING_HUMAN_REVIEW
    payload = report.to_dict()
    assert payload["human_review_required"]
    assert payload["automatic_threshold_change_permitted"] is False
    assert payload["policy_promotion_authorized"] is False
    assert payload["performance_claims_permitted"] is False


def test_insufficient_elapsed_time_or_cycles_remains_in_progress() -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    registration = _registration(protocol)
    report = evaluate_paper_experiment(
        protocol, registration,
        tuple(_observation(registration, protocol, index) for index in range(10)),
        evaluated_at=NOW + timedelta(days=15),
    )
    assert report.state is PaperExperimentState.IN_PROGRESS


def test_mid_run_protocol_or_code_drift_blocks_without_rewriting_history() -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    registration = _registration(protocol)
    drifted_protocol = replace(protocol, maximum_missing_cycles=1)
    observation = replace(_observation(registration, protocol, 0), code_version="b" * 40)
    report = evaluate_paper_experiment(
        drifted_protocol, registration, (observation,), evaluated_at=NOW + timedelta(days=1)
    )
    assert report.state is PaperExperimentState.BLOCKED
    assert "protocol fingerprint drift" in report.blockers
    assert "observation code-version drift" in report.blockers


def test_missing_data_unreconciled_or_unreconstructable_benchmark_blocks() -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    registration = _registration(protocol)
    observations = (
        _observation(registration, protocol, 0, missing=True),
        _observation(registration, protocol, 1, missing=True),
        _observation(registration, protocol, 2, missing=True),
        _observation(registration, protocol, 3, reconciled=False),
        _observation(registration, protocol, 4, benchmark=False),
    )
    report = evaluate_paper_experiment(
        protocol, registration, observations, evaluated_at=NOW + timedelta(days=5)
    )
    assert report.state is PaperExperimentState.BLOCKED
    assert {"missing-data allowance exceeded", "unreconciled observation", "benchmark is not reconstructable"} <= set(report.blockers)


def test_duplicate_cycle_is_blocked_and_restart_replay_is_idempotent_in_store(tmp_path) -> None:
    protocol = load_paper_experiment_protocol(PROTOCOL_PATH)
    registration = _registration(protocol)
    first = _observation(registration, protocol, 0)
    duplicate_date = replace(_observation(registration, protocol, 1), operation_date=first.operation_date)
    report = evaluate_paper_experiment(
        protocol, registration, (first, duplicate_date), evaluated_at=NOW + timedelta(days=2)
    )
    assert report.state is PaperExperimentState.BLOCKED
    assert "duplicate operating date" in report.blockers

    store = SQLitePaperExperimentStore(tmp_path / "experiment.db")
    payload = protocol.to_dict()
    store.append(identifier=protocol.version, event_type="protocol", recorded_at=NOW, payload=payload)
    store.append(identifier=protocol.version, event_type="protocol", recorded_at=NOW, payload=payload)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_experiment_events").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM paper_experiment_events")


def test_private_registration_cli_requires_gate_evidence_and_persists_once(tmp_path) -> None:
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps({gate: True for gate in REQUIRED_LAUNCH_GATES}), encoding="utf-8")
    database = tmp_path / "experiment.db"
    args = (
        "paper-experiment-register", "--protocol", str(PROTOCOL_PATH),
        "--gate-evidence", str(gates), "--code-version", SHA,
        "--deployed-git-sha", SHA, "--start-date", (date.today() + timedelta(days=1)).isoformat(),
        "--database", str(database),
    )
    assert cli_main(args) == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_experiment_events").fetchone()[0] == 1
