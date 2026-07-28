"""Tests for the three non-substitutable paper execution authorities."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance import (
    ControlledPaperTestEligibilityPackage,
    ControlledPaperTestEntryDecision,
    PaperTestEligibilityState,
    PaperTestEntryDecisionState,
    PaperTradingControlEvent,
    PaperTradingControlState,
    PaperTradingLaunchError,
    PaperTradingLaunchReport,
    PaperTradingLaunchState,
    SQLitePaperTestEntryGovernanceStore,
    SQLitePaperTradingControlStore,
    SQLitePaperTradingLaunchStore,
    require_combined_paper_execution_authorization,
)
from run_paper_trading_control import main as control_main

NOW = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
BASELINE = "test-baseline:combined-paper-authority.v1"
PROCESS = "capital-intelligence-investment-process.v1-test"
CODE = "commit:combined-paper-authority"


def _package(
    *,
    identifier: str = "paper-test-eligibility:combined:1",
    state: PaperTestEligibilityState = PaperTestEligibilityState.ELIGIBLE,
    assembled_at: datetime | None = None,
) -> ControlledPaperTestEligibilityPackage:
    blocked = state is PaperTestEligibilityState.BLOCKED
    return ControlledPaperTestEligibilityPackage(
        identifier=identifier,
        assembled_at=assembled_at or (NOW - timedelta(minutes=10)),
        state=state,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        process_freeze_identifier="process-freeze:test",
        readiness_report_identifier="product-readiness:test",
        campaign_report_identifier="paper-campaign:test",
        recovery_report_identifier="recovery:test",
        stage_binding_approval_identifier="stage-binding:test",
        blockers=("new operating blocker",) if blocked else (),
        evidence_identifiers=(
            "process-freeze:test",
            "product-readiness:test",
            "paper-campaign:test",
            "recovery:test",
            "stage-binding:test",
        ),
    )


def _decision(
    package: ControlledPaperTestEligibilityPackage,
    *,
    identifier: str = "paper-test-entry-decision:approved:1",
    state: PaperTestEntryDecisionState = PaperTestEntryDecisionState.APPROVED,
    decided_at: datetime | None = None,
) -> ControlledPaperTestEntryDecision:
    decided = decided_at or (NOW - timedelta(minutes=8))
    return ControlledPaperTestEntryDecision(
        identifier=identifier,
        state=state,
        decided_at=decided,
        effective_at=decided,
        expires_at=NOW + timedelta(days=1),
        package_identifier=package.identifier,
        package_fingerprint=package.fingerprint,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        cohort_identifier="paper-cohort:alpha.1",
        governance_identifier="authority:paper-test-release",
        approver_role="paper_test_release_authority",
        independent_validator_identifier="authority:independent-validation",
        rationale="Approve the exact controlled paper-test package.",
        limitations=("paper-only controlled cohort",),
    )


def _launch() -> PaperTradingLaunchReport:
    return PaperTradingLaunchReport(
        identifier="paper-trading-launch:combined:1",
        assessed_at=NOW - timedelta(minutes=7),
        valid_until=NOW + timedelta(hours=12),
        state=PaperTradingLaunchState.READY,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        policy_version="paper-trading-launch-policy.v1",
        blockers=(),
        evidence_identifiers=(
            "burn-in:test",
            "provider-health:test",
            "execution-calibration:test",
        ),
        maximum_drawdown_fraction=0.20,
        maximum_single_batch_turnover=0.35,
    )


def _seed(
    tmp_path: Path,
):
    entry_store = SQLitePaperTestEntryGovernanceStore(tmp_path / "entry.db")
    package = _package()
    decision = _decision(package)
    entry_store.append_package(package)
    entry_store.append_decision(decision, package=package)

    launch_store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    launch = _launch()
    launch_store.append(launch)

    control_store = SQLitePaperTradingControlStore(tmp_path / "control.db")
    active = PaperTradingControlEvent(
        identifier="paper-runtime-control:active:1",
        state=PaperTradingControlState.ACTIVE,
        effective_at=NOW - timedelta(minutes=6),
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        reason="Activate the approved and operationally ready cohort.",
        authority_identifiers=("authority:risk-operations",),
        launch_report_identifier=launch.identifier,
    )
    control_store.append(active)
    return entry_store, launch_store, control_store, package, decision, launch


def test_combined_authority_requires_human_entry_launch_and_runtime_switch(
    tmp_path: Path,
) -> None:
    entry_store, launch_store, control_store, package, decision, launch = _seed(
        tmp_path
    )

    authorization = require_combined_paper_execution_authorization(
        entry_store=entry_store,
        launch_store=launch_store,
        control_store=control_store,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        as_of=NOW,
    )

    assert authorization.entry_package.identifier == package.identifier
    assert authorization.entry_decision.identifier == decision.identifier
    assert authorization.launch_report.identifier == launch.identifier
    assert authorization.cohort_identifier == "paper-cohort:alpha.1"
    assert package.fingerprint in authorization.source_identifiers


def test_latest_suspension_immediately_blocks_execution(tmp_path: Path) -> None:
    entry_store, launch_store, control_store, package, _, _ = _seed(tmp_path)
    entry_store.append_decision(
        _decision(
            package,
            identifier="paper-test-entry-decision:suspended:2",
            state=PaperTestEntryDecisionState.SUSPENDED,
            decided_at=NOW + timedelta(minutes=1),
        ),
        package=package,
    )

    with pytest.raises(PaperTradingLaunchError, match="not approved"):
        require_combined_paper_execution_authorization(
            entry_store=entry_store,
            launch_store=launch_store,
            control_store=control_store,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            as_of=NOW + timedelta(minutes=2),
        )


def test_newer_blocked_package_supersedes_approved_older_package(
    tmp_path: Path,
) -> None:
    entry_store, launch_store, control_store, _, _, _ = _seed(tmp_path)
    entry_store.append_package(
        _package(
            identifier="paper-test-eligibility:combined:blocked:2",
            state=PaperTestEligibilityState.BLOCKED,
            assembled_at=NOW + timedelta(minutes=1),
        )
    )

    with pytest.raises(PaperTradingLaunchError, match="package is blocked"):
        require_combined_paper_execution_authorization(
            entry_store=entry_store,
            launch_store=launch_store,
            control_store=control_store,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            as_of=NOW + timedelta(minutes=2),
        )


def test_later_runtime_halt_blocks_execution(tmp_path: Path) -> None:
    entry_store, launch_store, control_store, _, _, _ = _seed(tmp_path)
    control_store.append(
        PaperTradingControlEvent(
            identifier="paper-runtime-control:halted:2",
            state=PaperTradingControlState.HALTED,
            effective_at=NOW + timedelta(minutes=1),
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            reason="Exercise the emergency runtime halt.",
            authority_identifiers=("authority:risk-operations",),
        )
    )

    with pytest.raises(PaperTradingLaunchError, match="halted"):
        require_combined_paper_execution_authorization(
            entry_store=entry_store,
            launch_store=launch_store,
            control_store=control_store,
            baseline_identifier=BASELINE,
            process_version=PROCESS,
            code_version=CODE,
            as_of=NOW + timedelta(minutes=2),
        )


def test_runtime_activation_cli_requires_and_records_human_entry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry_store = SQLitePaperTestEntryGovernanceStore(tmp_path / "entry.db")
    package = _package()
    decision = _decision(package)
    entry_store.append_package(package)
    entry_store.append_decision(decision, package=package)
    launch_store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    launch_store.append(_launch())

    result = control_main(
        (
            "activate",
            "--baseline-identifier",
            BASELINE,
            "--process-version",
            PROCESS,
            "--code-version",
            CODE,
            "--effective-at",
            NOW.isoformat(),
            "--identifier",
            "paper-runtime-control:cli:active",
            "--reason",
            "Reviewed runtime activation.",
            "--authority-identifier",
            "authority:risk-operations",
            "--entry-database",
            str(entry_store.path),
            "--launch-database",
            str(launch_store.path),
            "--control-database",
            str(tmp_path / "control.db"),
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["state"] == PaperTradingControlState.ACTIVE.value
    assert payload["human_entry_decision_identifier"] == decision.identifier
    assert payload["eligibility_package_identifier"] == package.identifier
    assert payload["eligibility_package_fingerprint"] == package.fingerprint
    assert payload["real_money_authorized"] is False


def test_runtime_activation_cli_fails_without_human_decision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry_store = SQLitePaperTestEntryGovernanceStore(tmp_path / "entry.db")
    entry_store.append_package(_package())
    launch_store = SQLitePaperTradingLaunchStore(tmp_path / "launch.db")
    launch_store.append(_launch())

    result = control_main(
        (
            "activate",
            "--baseline-identifier",
            BASELINE,
            "--process-version",
            PROCESS,
            "--code-version",
            CODE,
            "--effective-at",
            NOW.isoformat(),
            "--identifier",
            "paper-runtime-control:cli:blocked",
            "--reason",
            "This activation must fail.",
            "--authority-identifier",
            "authority:test",
            "--entry-database",
            str(entry_store.path),
            "--launch-database",
            str(launch_store.path),
            "--control-database",
            str(tmp_path / "control.db"),
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 4
    assert payload["state"] == PaperTradingControlState.HALTED.value
    assert "entry decision is unavailable" in payload["error"]
    assert payload["real_money_authorized"] is False
