"""Acceptance tests for immediate operational paper-launch certification."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance import (
    PaperTradingControlEvent,
    PaperTradingControlState,
    PaperTradingLaunchError,
    PaperTradingLaunchEvidence,
    PaperTradingLaunchEvaluator,
    PaperTradingLaunchIntegrityError,
    PaperTradingLaunchPolicy,
    PaperTradingLaunchState,
    SQLitePaperTradingControlStore,
    SQLitePaperTradingLaunchStore,
    require_paper_execution_authorization,
)
from run_paper_trading_launch import main as launch_main

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 3, 21, 0, tzinfo=timezone.utc)
BASELINE = "test-baseline:paper-launch.v1"
PROCESS = "capital-intelligence-investment-process.v1-test"
CODE = "commit:paper-launch-test"


def _evidence(**overrides) -> PaperTradingLaunchEvidence:
    values = {
        "identifier": "paper-launch-evidence:ready",
        "observed_at": NOW,
        "knowledge_cutoff": NOW,
        "window_start": NOW,
        "window_end": NOW,
        "baseline_identifier": BASELINE,
        "process_version": PROCESS,
        "code_version": CODE,
        "portfolio_count": 1,
        "portfolio_code": "COMPOUNDING",
        "starting_capital": 250_000.0,
        "base_currency": "USD",
        "paper_only_disclosures_verified": True,
        "live_broker_credentials_present": False,
        "canonical_portfolio_integrity_verified": True,
        "eligible_universe_integrity_verified": True,
        "execution_store_integrity_verified": True,
        "scheduled_cycles": 1,
        "successful_cycles": 1,
        "point_in_time_cycles": 1,
        "complete_universe_cycles": 1,
        "required_provider_checks": 500,
        "successful_required_provider_checks": 500,
        "shadow_execution_scenarios": 12,
        "reconciled_shadow_execution_scenarios": 12,
        "execution_cost_error_bps": 10.0,
        "unresolved_orders": 0,
        "duplicate_fill_events": 0,
        "negative_cash_events": 0,
        "stale_quote_acceptances": 0,
        "unresolved_critical_incidents": 0,
        "data_integrity_failures": 0,
        "reconciliation_failures": 0,
        "backup_restore_exercises": 1,
        "scheduler_replay_exercises": 1,
        "kill_switch_exercises": 2,
        "provider_failover_exercises": 1,
        "market_session_exercises": 3,
        "partial_fill_retry_exercises": 1,
        "corporate_action_replay_exercises": 1,
        "fx_revaluation_exercises": 1,
        "production_binding_approval_identifier": "binding-approval:test",
        "recovery_certification_identifier": "recovery:test",
        "execution_calibration_identifier": "execution-calibration:test",
        "execution_policy_version": "multi-asset-paper-execution.v1",
        "data_readiness_identifier": "combined-data-readiness:test",
        "product_readiness_identifier": "prelaunch-readiness:test",
        "evidence_identifiers": (
            "launch-cycle:test",
            "provider-health:test",
            "shadow-execution:test",
        ),
        "source_identifiers": (
            "portfolio-chain:test",
            "universe-chain:test",
            "execution-chain:test",
        ),
    }
    values.update(overrides)
    return PaperTradingLaunchEvidence(**values)


def test_policy_and_example_evidence_match_schema() -> None:
    import jsonschema

    policy = PaperTradingLaunchPolicy.from_dict(
        json.loads(
            (ROOT / "config" / "paper_trading_launch_policy.json").read_text(
                encoding="utf-8"
            )
        )
    )
    payload = json.loads(
        (
            ROOT
            / "docs"
            / "examples"
            / "paper_trading_launch_evidence.example.json"
        ).read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "schemas" / "paper_trading_launch_evidence.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.Draft202012Validator(schema).validate(payload)
    assert policy.required_starting_capital == 250_000.0
    assert policy.required_portfolio_code == "COMPOUNDING"
    assert policy.required_portfolio_count == 1
    assert policy.minimum_burn_in_days == 0
    assert policy.minimum_scheduled_cycles == 1


def test_complete_immediate_evidence_is_ready_but_paper_only() -> None:
    report = PaperTradingLaunchEvaluator().evaluate(_evidence())

    assert report.state is PaperTradingLaunchState.READY
    assert report.blockers == ()
    assert _evidence().burn_in_days == 0.0
    assert report.maximum_drawdown_fraction == 0.20
    assert report.maximum_single_batch_turnover == 0.35
    assert report.real_money_authorized is False
    assert report.performance_claims_permitted is False


def test_any_operating_or_portfolio_failure_blocks_launch() -> None:
    report = PaperTradingLaunchEvaluator().evaluate(
        _evidence(
            identifier="paper-launch-evidence:blocked",
            window_start=NOW,
            portfolio_count=2,
            starting_capital=249_999.0,
            successful_cycles=0,
            successful_required_provider_checks=490,
            reconciled_shadow_execution_scenarios=11,
            execution_cost_error_bps=30.0,
            unresolved_orders=1,
            stale_quote_acceptances=1,
            live_broker_credentials_present=True,
        )
    )

    assert report.state is PaperTradingLaunchState.BLOCKED
    joined = " ".join(report.blockers)
    for expected in (
        "portfolio_count",
        "starting_capital",
        "successful_cycle_ratio",
        "required_provider_success_ratio",
        "reconciled_shadow_execution_ratio",
        "execution_cost_error_bps",
        "unresolved_orders",
        "stale_quote_acceptances",
        "live broker credentials",
    ):
        assert expected in joined


def test_latest_blocked_assessment_supersedes_prior_ready_report(
    tmp_path: Path,
) -> None:
    store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    store.append(PaperTradingLaunchEvaluator().evaluate(_evidence()))
    blocked = PaperTradingLaunchEvaluator().evaluate(
        replace(
            _evidence(),
            identifier="paper-launch-evidence:newer-blocked",
            observed_at=NOW + timedelta(minutes=1),
            knowledge_cutoff=NOW + timedelta(minutes=1),
            window_end=NOW + timedelta(minutes=1),
            unresolved_orders=1,
        )
    )
    store.append(blocked)

    assert blocked.state is PaperTradingLaunchState.BLOCKED
    assert (
        store.latest_ready(
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            as_of=NOW + timedelta(minutes=2),
        )
        is None
    )


def test_launch_and_runtime_control_stores_are_append_only(
    tmp_path: Path,
) -> None:
    launch_store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    launch = PaperTradingLaunchEvaluator().evaluate(_evidence())
    control_store = SQLitePaperTradingControlStore(tmp_path / "control.db")
    control = PaperTradingControlEvent(
        identifier="paper-control:activate:test",
        state=PaperTradingControlState.ACTIVE,
        effective_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        reason="Exercise the runtime switch.",
        authority_identifiers=("authority:risk",),
        launch_report_identifier=launch.identifier,
    )

    assert launch_store.append(launch) == 1
    assert launch_store.append(launch) == 1
    assert control_store.append(control) == 1
    assert control_store.append(control) == 1
    assert launch_store.verify_integrity()
    assert control_store.verify_integrity()

    with sqlite3.connect(launch_store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE paper_trading_launch_reports SET payload_json='{}' "
                "WHERE sequence=1"
            )
        connection.execute("DROP TRIGGER paper_trading_launch_reports_no_update")
        connection.execute(
            "UPDATE paper_trading_launch_reports SET payload_json='{}' WHERE sequence=1"
        )

    with pytest.raises(PaperTradingLaunchIntegrityError):
        launch_store.verify_integrity()


def test_operational_launch_helper_requires_active_runtime_switch(
    tmp_path: Path,
) -> None:
    launch_store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    control_store = SQLitePaperTradingControlStore(tmp_path / "control.db")
    launch = PaperTradingLaunchEvaluator().evaluate(_evidence())
    launch_store.append(launch)

    with pytest.raises(PaperTradingLaunchError, match="halted"):
        require_paper_execution_authorization(
            launch_store=launch_store,
            control_store=control_store,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            as_of=NOW,
        )

    control_store.append(
        PaperTradingControlEvent(
            identifier="paper-control:active:test",
            state=PaperTradingControlState.ACTIVE,
            effective_at=NOW,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            reason="Exercise activation.",
            authority_identifiers=("authority:risk",),
            launch_report_identifier=launch.identifier,
        )
    )
    authorization = require_paper_execution_authorization(
        launch_store=launch_store,
        control_store=control_store,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        as_of=NOW + timedelta(minutes=1),
    )
    assert authorization.launch_report.identifier == launch.identifier


def test_expiry_and_version_mismatch_fail_closed(tmp_path: Path) -> None:
    launch_store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    control_store = SQLitePaperTradingControlStore(tmp_path / "control.db")
    launch = PaperTradingLaunchEvaluator(
        PaperTradingLaunchPolicy(authorization_ttl_hours=1)
    ).evaluate(_evidence())
    launch_store.append(launch)
    control_store.append(
        PaperTradingControlEvent(
            identifier="paper-control:active:expiry-test",
            state=PaperTradingControlState.ACTIVE,
            effective_at=NOW,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            reason="Temporary activation.",
            authority_identifiers=("authority:test",),
            launch_report_identifier=launch.identifier,
        )
    )

    with pytest.raises(PaperTradingLaunchError, match="unavailable"):
        require_paper_execution_authorization(
            launch_store=launch_store,
            control_store=control_store,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            as_of=NOW + timedelta(hours=2),
        )
    with pytest.raises(PaperTradingLaunchError, match="unavailable"):
        require_paper_execution_authorization(
            launch_store=launch_store,
            control_store=control_store,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version="commit:other",
            as_of=NOW + timedelta(minutes=1),
        )


def test_launch_cli_persists_credential_safe_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_evidence().to_dict()), encoding="utf-8")

    assert (
        launch_main(
            (
                "--evidence",
                str(evidence_path),
                "--database",
                str(tmp_path / "launch.db"),
                "--require-ready",
                "--compact",
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == PaperTradingLaunchState.READY.value
    assert payload["secret_values_disclosed"] is False
    assert payload["real_money_authorized"] is False
