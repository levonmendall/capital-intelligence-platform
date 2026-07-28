from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.data_readiness import DataDomain
from governance.provider_activation import (
    ProviderActivation,
    SQLiteProviderActivationStore,
)
from operations.execution_calibration import (
    ExecutionCalibrationReport,
    ExecutionCalibrationState,
)
from operations.paper_readiness_status import (
    PaperReadinessObjectiveState,
    PaperReadinessStatusAssembler,
    PaperReadinessStatusInputs,
)
from operations.provider_reconciliation import (
    ProviderReconciliationReport,
    ProviderReconciliationState,
)
from run_paper_readiness_status import main as status_main

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)
BASELINE = "test-baseline:status.v1"
PROCESS = "capital-intelligence-investment-process.v1-test"
CODE = "commit:status-test"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _evidence(tmp_path: Path):
    binding = tmp_path / "provider-bindings.json"
    _write_json(binding, {"bindings": []})
    requirements = tmp_path / "provider-requirements.json"
    _write_json(
        requirements,
        {
            "schema_version": "paper-readiness-provider-requirements.v2",
            "providers": [
                {
                    "name": "test provider",
                    "provider_identifier": "test-provider",
                    "required": True,
                    "activation_required": True,
                    "credential_environments": ["TEST_PROVIDER_TOKEN"],
                    "binding_environments": ["TEST_PROVIDER_BINDINGS"],
                }
            ],
        },
    )
    activation_store = SQLiteProviderActivationStore(tmp_path / "provider-activation.db")
    activation_store.append(
        ProviderActivation(
            identifier="provider-activation:test-provider:1",
            provider_identifier="test-provider",
            provider_name="Test Provider",
            enabled=True,
            approved_domains=(DataDomain.MARKET_PRICES,),
            authoritative_domains=(DataDomain.MARKET_PRICES,),
            usage_rights_approved=True,
            point_in_time_supported=True,
            historical_coverage_supported=True,
            provenance_complete=True,
            service_level_defined=True,
            storage_and_backup_approved=True,
            derived_analytics_approved=True,
            paper_simulation_approved=True,
            certification_identifier="provider-certification:test",
            approved_by="data-governance:test",
            rationale="Synthetic readiness-status acceptance evidence.",
            approved_at=NOW - timedelta(days=1),
            effective_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(days=1),
            source_identifiers=("license-approval:test",),
        )
    )
    reconciliation = ProviderReconciliationReport(
        identifier="provider-reconciliation:test",
        evaluated_at=NOW,
        state=ProviderReconciliationState.PASSED,
        backfill_report_identifier="provider-backfill:test",
        plan_identifier="provider-plan:test",
        artifact_count=1,
        reconciled_artifact_count=1,
        payload_item_count=10,
        empty_artifact_count=0,
        duplicate_logical_window_count=0,
        blockers=(),
        warnings=(),
        artifact_hashes=("a" * 64,),
    )
    reconciliation_path = tmp_path / "reconciliation.json"
    _write_json(reconciliation_path, reconciliation.to_dict())
    calibration = ExecutionCalibrationReport(
        identifier="execution-calibration:test",
        evaluated_at=NOW,
        state=ExecutionCalibrationState.PASSED,
        policy_version="paper-execution-calibration-policy.v1",
        execution_policy_version="multi-asset-paper-execution.v1",
        sample_count=12,
        asset_class_count=3,
        reconciled_sample_count=12,
        stale_sample_count=0,
        mean_absolute_error_bps=5.0,
        p95_absolute_error_bps=7.0,
        maximum_absolute_error_bps=9.0,
        blockers=(),
        sample_identifiers=tuple(f"sample:{item}" for item in range(12)),
        source_identifiers=("quote-evidence:test",),
    )
    calibration_path = tmp_path / "calibration.json"
    _write_json(calibration_path, calibration.to_dict())
    return (
        requirements,
        binding,
        activation_store.path,
        reconciliation_path,
        calibration_path,
    )


def test_status_completes_only_supported_objectives(tmp_path: Path) -> None:
    requirements, binding, activation_db, reconciliation, calibration = _evidence(
        tmp_path
    )
    assembler = PaperReadinessStatusAssembler(
        {
            "TEST_PROVIDER_TOKEN": "secret-value-not-reported",
            "TEST_PROVIDER_BINDINGS": str(binding),
        }
    )

    report = assembler.assemble(
        identifier="paper-readiness-status:test",
        evaluated_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        inputs=PaperReadinessStatusInputs(
            provider_requirements=requirements,
            provider_activation_database=activation_db,
            reconciliation_reports=(reconciliation,),
            execution_calibration_report=calibration,
        ),
    )
    by_name = {item.name: item for item in report.objectives}

    provider_objective = by_name["licensed_and_certified_market_data_providers"]
    assert provider_objective.complete
    assert "provider-activation:test-provider:1" in (
        provider_objective.evidence_identifiers
    )
    assert by_name["completed_backfills_and_reconciliation"].complete
    assert by_name["execution_price_and_cost_calibration"].complete
    assert by_name["reviewed_production_bindings_and_credentials"].state is (
        PaperReadinessObjectiveState.BLOCKED
    )
    assert by_name["five_day_live_burn_in_and_required_exercises"].state is (
        PaperReadinessObjectiveState.BLOCKED
    )
    assert by_name["human_approval_of_exact_eligibility_package_and_cohort"].state is (
        PaperReadinessObjectiveState.BLOCKED
    )
    payload = report.to_dict()
    assert payload["complete"] is False
    assert payload["secret_values_disclosed"] is False
    assert "secret-value-not-reported" not in json.dumps(payload)


def test_status_cli_fails_closed_without_operating_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    requirements, _, _, _, _ = _evidence(tmp_path)

    exit_code = status_main(
        (
            "--baseline-identifier",
            BASELINE,
            "--process-version",
            PROCESS,
            "--code-version",
            CODE,
            "--evaluated-at",
            NOW.isoformat(),
            "--provider-requirements",
            str(requirements),
            "--provider-activation-database",
            str(tmp_path / "empty-provider-activation.db"),
            "--stage-binding-database",
            str(tmp_path / "stage-binding.db"),
            "--campaign-database",
            str(tmp_path / "campaign.db"),
            "--entry-database",
            str(tmp_path / "entry.db"),
            "--launch-database",
            str(tmp_path / "launch.db"),
            "--control-database",
            str(tmp_path / "control.db"),
            "--require-complete",
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["state"] == "blocked"
    assert payload["paper_test_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert len(payload["objectives"]) == 8
