"""Acceptance tests for human-governed controlled paper-test entry."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance.paper_test_entry import (
    ControlledPaperTestEligibilityPackage,
    ControlledPaperTestEntryDecision,
    InvestmentProcessFreeze,
    PaperTestEligibilityState,
    PaperTestEntryDecisionState,
    PaperTestEntryGovernanceError,
    PaperTestEntryPackageAssembler,
    ProcessFreezeState,
    SQLitePaperTestEntryGovernanceStore,
    canonical_process_bundle_sha256,
)
from governance.product_readiness import (
    ProductTestReadiness,
    ProductTestReadinessReport,
)
from governance.stage_binding_approval import (
    StageBindingApproval,
    StageBindingApprovalState,
)
from operations.paper_test_campaign import (
    FailureScenarioKind,
    PaperTestCampaignBaseline,
    PaperTestCampaignReport,
    PaperTestCampaignState,
)
from operations.recovery_drill import RecoveryDrillReport, RecoveryDrillStatus

UTC = timezone.utc
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
BASELINE_ID = "test-baseline:universal-paper-alpha.1"
PROCESS_VERSION = "capital-intelligence-investment-process.v1"
CODE_VERSION = "commit:test-ready"
PLAN_HASH = "a" * 64
BINDING_HASH = "b" * 64
CONFIG_HASH = "c" * 64
PROCESS_HASH = "d" * 64


def _freeze(
    *,
    state: ProcessFreezeState = ProcessFreezeState.FROZEN,
    expires_at: datetime = NOW + timedelta(days=30),
    binding_hash: str = BINDING_HASH,
) -> InvestmentProcessFreeze:
    return InvestmentProcessFreeze(
        identifier=f"process-freeze:{state.value}:1",
        state=state,
        recorded_at=NOW - timedelta(days=2),
        effective_at=NOW - timedelta(days=1),
        expires_at=expires_at,
        baseline_identifier=BASELINE_ID,
        process_version=PROCESS_VERSION,
        code_version=CODE_VERSION,
        process_bundle_sha256=PROCESS_HASH,
        operation_plan_sha256=PLAN_HASH,
        stage_bindings_sha256=binding_hash,
        configuration_sha256=CONFIG_HASH,
        data_manifest_identifier="all-markets-data-manifest.v1",
        governance_identifier="governance:investment-process:committee-a",
        approver_role="investment_process_governance",
        independent_validation_identifier="validation:independent:1",
        evidence_identifiers=("evidence:process-review:1",),
        limitations=("Controlled paper testing only.",),
    )


def _readiness(
    state: ProductTestReadiness = ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST,
) -> ProductTestReadinessReport:
    return ProductTestReadinessReport(
        identifier="readiness:report:1",
        assessed_at=NOW - timedelta(minutes=10),
        state=state,
        baseline_identifier=BASELINE_ID,
        process_version=PROCESS_VERSION,
        blockers=() if state is ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST else ("data",),
        development_items=("Later development continues on newer commits.",),
        evidence_identifiers=("evidence:readiness:1",),
    )


def _baseline() -> PaperTestCampaignBaseline:
    return PaperTestCampaignBaseline(
        identifier=BASELINE_ID,
        created_at=NOW - timedelta(days=10),
        effective_date=date(2026, 7, 19),
        process_version=PROCESS_VERSION,
        code_version=CODE_VERSION,
        operation_plan_hash=PLAN_HASH,
        stage_bindings_hash=BINDING_HASH,
        configuration_hash=CONFIG_HASH,
        data_manifest_identifier="all-markets-data-manifest.v1",
        required_consecutive_days=5,
    )


def _campaign(
    baseline: PaperTestCampaignBaseline,
    state: PaperTestCampaignState = PaperTestCampaignState.SATISFIED,
) -> PaperTestCampaignReport:
    scenarios = tuple(FailureScenarioKind)
    return PaperTestCampaignReport(
        identifier=f"campaign:report:{state.value}:1",
        baseline_identifier=baseline.identifier,
        baseline_fingerprint=baseline.fingerprint,
        evaluated_at=NOW - timedelta(minutes=8),
        state=state,
        credited_dates=tuple(date(2026, 7, day) for day in range(23, 28)),
        consecutive_day_count=5,
        required_consecutive_days=5,
        passed_scenarios=scenarios if state is PaperTestCampaignState.SATISFIED else (),
        missing_scenarios=() if state is PaperTestCampaignState.SATISFIED else scenarios,
        failed_scenarios=(),
        blockers=() if state is PaperTestCampaignState.SATISFIED else ("campaign incomplete",),
        evidence_identifiers=("evidence:campaign:1",),
    )


def _recovery(
    status: RecoveryDrillStatus = RecoveryDrillStatus.PASSED,
) -> RecoveryDrillReport:
    return RecoveryDrillReport(
        identifier=f"recovery:report:{status.value}:1",
        expectation_identifier="recovery:expectation:1",
        archive_identifier="backup:canonical:1",
        executed_at=NOW - timedelta(minutes=6),
        status=status,
        baseline_identifier=BASELINE_ID,
        process_version=PROCESS_VERSION,
        code_version=CODE_VERSION,
        restored_authorities=("institutional_journal", "canonical_portfolio"),
        integrity_verified_authorities=("institutional_journal", "canonical_portfolio"),
        passed_probe_identifiers=("probe:decision", "probe:portfolio"),
        failed_probe_identifiers=() if status is RecoveryDrillStatus.PASSED else ("probe:decision",),
        recovery_seconds=30,
        data_loss_seconds=0,
        production_mutation_count=0,
        blockers=() if status is RecoveryDrillStatus.PASSED else ("lineage probe failed",),
        evidence_identifiers=("evidence:recovery:1",),
    )


def _binding(*, binding_hash: str = BINDING_HASH) -> StageBindingApproval:
    return StageBindingApproval(
        identifier="binding-approval:approved:1",
        binding_sha256=binding_hash,
        baseline_identifier=BASELINE_ID,
        process_version=PROCESS_VERSION,
        code_version=CODE_VERSION,
        state=StageBindingApprovalState.APPROVED,
        approved_at=NOW - timedelta(days=2),
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
        governance_identifier="governance:deployment:1",
        approver_role="deployment_governance",
        approved_modules=("run_daily_stage_adapter",),
        required_secret_names=("FRED_API_KEY",),
        rationale="Reviewed paper-only production binding.",
    )


def _package(
    *,
    freeze: InvestmentProcessFreeze | None = None,
    readiness: ProductTestReadinessReport | None = None,
    campaign_state: PaperTestCampaignState = PaperTestCampaignState.SATISFIED,
    recovery_status: RecoveryDrillStatus = RecoveryDrillStatus.PASSED,
) -> ControlledPaperTestEligibilityPackage:
    baseline = _baseline()
    return PaperTestEntryPackageAssembler().assemble(
        freeze=freeze or _freeze(),
        readiness=readiness or _readiness(),
        baseline=baseline,
        campaign=_campaign(baseline, campaign_state),
        recovery=_recovery(recovery_status),
        stage_binding_approval=_binding(
            binding_hash=(freeze or _freeze()).stage_bindings_sha256
        ),
        assembled_at=NOW,
    )


def _decision(
    package: ControlledPaperTestEligibilityPackage,
    *,
    state: PaperTestEntryDecisionState = PaperTestEntryDecisionState.APPROVED,
    identifier: str = "paper-test-entry-decision:1",
) -> ControlledPaperTestEntryDecision:
    return ControlledPaperTestEntryDecision(
        identifier=identifier,
        state=state,
        decided_at=NOW,
        effective_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(days=14),
        package_identifier=package.identifier,
        package_fingerprint=package.fingerprint,
        baseline_identifier=package.baseline_identifier,
        process_version=package.process_version,
        code_version=package.code_version,
        cohort_identifier="controlled-paper-cohort:alpha-1",
        governance_identifier="governance:paper-test-release:1",
        approver_role="paper_test_release_authority",
        independent_validator_identifier="validation:paper-test:independent-1",
        rationale="Authorize the exact immutable baseline for a limited paper cohort.",
        limitations=("Paper-only; no broker connectivity or real-money activity.",),
    )


def test_complete_authorities_create_eligible_package() -> None:
    package = _package()
    assert package.state is PaperTestEligibilityState.ELIGIBLE
    assert package.blockers == ()
    assert package.to_dict()["paper_test_authorized"] is False
    assert package.fingerprint == ControlledPaperTestEligibilityPackage.from_dict(
        package.to_dict()
    ).fingerprint


def test_authority_drift_and_failed_evidence_block_package() -> None:
    freeze = _freeze(binding_hash="e" * 64)
    package = _package(
        freeze=freeze,
        readiness=_readiness(ProductTestReadiness.BLOCKED),
        campaign_state=PaperTestCampaignState.IN_PROGRESS,
        recovery_status=RecoveryDrillStatus.FAILED,
    )
    assert package.state is PaperTestEligibilityState.BLOCKED
    assert "stage-binding digest does not match the frozen baseline" in package.blockers
    assert "canonical product-test readiness is not satisfied" in package.blockers
    assert "burn-in and failure campaign is not satisfied" in package.blockers
    assert "canonical recovery drill is not passing" in package.blockers


@pytest.mark.parametrize(
    "freeze",
    (
        _freeze(expires_at=NOW - timedelta(seconds=1)),
        _freeze(state=ProcessFreezeState.SUSPENDED),
    ),
)
def test_inactive_process_freeze_blocks_package(freeze: InvestmentProcessFreeze) -> None:
    package = _package(freeze=freeze)
    assert package.state is PaperTestEligibilityState.BLOCKED
    assert "investment process freeze is not active" in package.blockers


def test_approved_decision_is_cohort_bound_and_paper_only(tmp_path: Path) -> None:
    store = SQLitePaperTestEntryGovernanceStore(tmp_path / "governance.db")
    package = _package()
    decision = _decision(package)
    assert store.append_freeze(_freeze()) == 1
    assert store.append_package(package) == 2
    assert store.append_decision(decision, package=package) == 3
    assert decision.active_at(NOW + timedelta(minutes=2))
    payload = decision.to_dict()
    assert payload["controlled_paper_test_authorized"] is True
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    assert payload["broker_connectivity_authorized"] is False
    assert payload["performance_claims_permitted"] is False


def test_blocked_package_cannot_be_human_approved(tmp_path: Path) -> None:
    package = _package(freeze=_freeze(state=ProcessFreezeState.SUSPENDED))
    store = SQLitePaperTestEntryGovernanceStore(tmp_path / "governance.db")
    store.append_package(package)
    with pytest.raises(PaperTestEntryGovernanceError, match="cannot be approved"):
        store.append_decision(_decision(package), package=package)


def test_package_fingerprint_cannot_be_substituted(tmp_path: Path) -> None:
    package = _package()
    store = SQLitePaperTestEntryGovernanceStore(tmp_path / "governance.db")
    store.append_package(package)
    altered = replace(_decision(package), package_fingerprint="f" * 64)
    with pytest.raises(PaperTestEntryGovernanceError, match="fingerprint"):
        store.append_decision(altered, package=package)


def test_suspension_supersedes_prior_entry_decision(tmp_path: Path) -> None:
    package = _package()
    store = SQLitePaperTestEntryGovernanceStore(tmp_path / "governance.db")
    store.append_package(package)
    store.append_decision(_decision(package), package=package)
    suspended = _decision(
        package,
        state=PaperTestEntryDecisionState.SUSPENDED,
        identifier="paper-test-entry-decision:suspended",
    )
    store.append_decision(suspended, package=package)
    assert store.decisions(BASELINE_ID)[-1].controlled_paper_test_authorized is False


def test_process_and_release_roles_require_independent_validation() -> None:
    with pytest.raises(ValueError, match="independent validation"):
        replace(
            _freeze(),
            independent_validation_identifier="governance:investment-process:committee-a",
        )
    package = _package()
    with pytest.raises(ValueError, match="independent validation"):
        replace(
            _decision(package),
            independent_validator_identifier="governance:paper-test-release:1",
        )


def test_process_bundle_hash_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "GOVERNING_SPECIFICATION.md"
    second = tmp_path / "ARCHITECTURE.md"
    first.write_text("governing rule\n", encoding="utf-8")
    second.write_text("authority boundary\n", encoding="utf-8")
    initial = canonical_process_bundle_sha256((first, second))
    assert initial == canonical_process_bundle_sha256((second, first))
    second.write_text("changed authority boundary\n", encoding="utf-8")
    assert canonical_process_bundle_sha256((first, second)) != initial


def test_governance_history_is_idempotent_and_append_only(tmp_path: Path) -> None:
    store = SQLitePaperTestEntryGovernanceStore(tmp_path / "governance.db")
    freeze = _freeze()
    assert store.append_freeze(freeze) == 1
    assert store.append_freeze(freeze) == 1
    assert store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE paper_test_entry_governance_events "
                "SET payload_json='{}' WHERE sequence=1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM paper_test_entry_governance_events")
