"""Governed production stage-binding approval tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance.stage_binding_approval import (
    SQLiteStageBindingApprovalStore,
    StageBindingApproval,
    StageBindingApprovalError,
    StageBindingApprovalState,
    require_approved_stage_bindings,
    stage_binding_sha256,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _bindings(path: Path, *, altered: bool = False) -> Path:
    stages = {}
    names = (
        "provider_certification",
        "security_master_activation",
        "eligible_universe_publication",
        "complete_universe_screening",
        "production_context_assembly",
        "canonical_cio_cycle",
        "paper_construction_execution",
        "thesis_monitoring",
        "outcome_evaluation",
        "operational_evidence_review",
        "canonical_alert_delivery",
        "slo_assessment",
    )
    for index, name in enumerate(names):
        stages[name] = {
            "module": "run_validation_stage",
            "argv": ["--stage", name, "--token", "${PROVIDER_TOKEN}"],
            "output_fields": ["publication_identifier"],
            "retryable_exit_codes": [75],
            "timeout_seconds": 31 if altered and index == 0 else 30,
        }
    path.write_text(
        json.dumps(
            {
                "schema_version": "canonical-daily-stage-bindings.v1",
                "stages": stages,
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _approval(
    binding_path: Path,
    *,
    identifier: str = "binding-approval:1",
    state: StageBindingApprovalState = StageBindingApprovalState.APPROVED,
    effective_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime = NOW + timedelta(days=30),
) -> StageBindingApproval:
    return StageBindingApproval(
        identifier=identifier,
        binding_sha256=stage_binding_sha256(binding_path),
        baseline_identifier="paper-baseline:alpha-1",
        process_version="process:alpha-1",
        code_version="commit:alpha-1",
        state=state,
        approved_at=effective_at - timedelta(minutes=1),
        effective_at=effective_at,
        expires_at=expires_at,
        governance_identifier="governance:deployment-review:1",
        approver_role="deployment_governance",
        approved_modules=("run_validation_stage",),
        required_secret_names=("PROVIDER_TOKEN",),
        rationale="Reviewed twelve-stage paper-only deployment binding.",
    )


def test_exact_active_approval_and_required_secret_allow_validation(tmp_path: Path) -> None:
    binding_path = _bindings(tmp_path / "bindings.json")
    store = SQLiteStageBindingApprovalStore(tmp_path / "approvals.db")
    approval = _approval(binding_path)
    store.append(approval)

    resolved = require_approved_stage_bindings(
        binding_path,
        approval_database=store.path,
        baseline_identifier="paper-baseline:alpha-1",
        process_version="process:alpha-1",
        code_version="commit:alpha-1",
        evaluated_at=NOW,
        environ={"PROVIDER_TOKEN": "secret-value-is-not-stored"},
    )

    assert resolved == approval
    assert resolved.to_dict()["real_money_authorized"] is False
    assert "secret-value-is-not-stored" not in json.dumps(resolved.to_dict())


def test_altered_binding_hash_fails_closed(tmp_path: Path) -> None:
    binding_path = _bindings(tmp_path / "bindings.json")
    store = SQLiteStageBindingApprovalStore(tmp_path / "approvals.db")
    store.append(_approval(binding_path))
    _bindings(binding_path, altered=True)

    with pytest.raises(StageBindingApprovalError, match="no active exact approval"):
        require_approved_stage_bindings(
            binding_path,
            approval_database=store.path,
            baseline_identifier="paper-baseline:alpha-1",
            process_version="process:alpha-1",
            code_version="commit:alpha-1",
            evaluated_at=NOW,
            environ={"PROVIDER_TOKEN": "configured"},
        )


def test_missing_secret_or_version_mismatch_blocks(tmp_path: Path) -> None:
    binding_path = _bindings(tmp_path / "bindings.json")
    store = SQLiteStageBindingApprovalStore(tmp_path / "approvals.db")
    store.append(_approval(binding_path))

    with pytest.raises(StageBindingApprovalError, match="missing required secret"):
        require_approved_stage_bindings(
            binding_path,
            approval_database=store.path,
            baseline_identifier="paper-baseline:alpha-1",
            process_version="process:alpha-1",
            code_version="commit:alpha-1",
            evaluated_at=NOW,
            environ={},
        )
    with pytest.raises(StageBindingApprovalError, match="code_version"):
        require_approved_stage_bindings(
            binding_path,
            approval_database=store.path,
            baseline_identifier="paper-baseline:alpha-1",
            process_version="process:alpha-1",
            code_version="commit:changed",
            evaluated_at=NOW,
            environ={"PROVIDER_TOKEN": "configured"},
        )


def test_latest_suspension_or_expiry_supersedes_prior_approval(tmp_path: Path) -> None:
    binding_path = _bindings(tmp_path / "bindings.json")
    store = SQLiteStageBindingApprovalStore(tmp_path / "approvals.db")
    store.append(_approval(binding_path))
    store.append(
        _approval(
            binding_path,
            identifier="binding-approval:suspended",
            state=StageBindingApprovalState.SUSPENDED,
            effective_at=NOW - timedelta(minutes=10),
        )
    )

    with pytest.raises(StageBindingApprovalError, match="no active exact approval"):
        require_approved_stage_bindings(
            binding_path,
            approval_database=store.path,
            baseline_identifier="paper-baseline:alpha-1",
            process_version="process:alpha-1",
            code_version="commit:alpha-1",
            evaluated_at=NOW,
            environ={"PROVIDER_TOKEN": "configured"},
        )

    expired_path = _bindings(tmp_path / "expired.json")
    expired_store = SQLiteStageBindingApprovalStore(tmp_path / "expired.db")
    expired_store.append(
        _approval(
            expired_path,
            identifier="binding-approval:expired",
            expires_at=NOW - timedelta(seconds=1),
            effective_at=NOW - timedelta(days=2),
        )
    )
    with pytest.raises(StageBindingApprovalError, match="no active exact approval"):
        require_approved_stage_bindings(
            expired_path,
            approval_database=expired_store.path,
            baseline_identifier="paper-baseline:alpha-1",
            process_version="process:alpha-1",
            code_version="commit:alpha-1",
            evaluated_at=NOW,
            environ={"PROVIDER_TOKEN": "configured"},
        )


def test_secret_values_and_unapproved_modules_are_prohibited(tmp_path: Path) -> None:
    binding_path = _bindings(tmp_path / "bindings.json")
    with pytest.raises(ValueError, match="names, not values"):
        StageBindingApproval(
            identifier="binding-approval:bad-secret",
            binding_sha256=stage_binding_sha256(binding_path),
            baseline_identifier="baseline",
            process_version="process",
            code_version="code",
            state=StageBindingApprovalState.APPROVED,
            approved_at=NOW,
            effective_at=NOW,
            expires_at=NOW + timedelta(days=1),
            governance_identifier="governance:1",
            approver_role="deployment_governance",
            approved_modules=("run_validation_stage",),
            required_secret_names=("api_key=literal-secret",),
            rationale="invalid",
        )

    store = SQLiteStageBindingApprovalStore(tmp_path / "approvals.db")
    store.append(
        StageBindingApproval(
            identifier="binding-approval:wrong-module",
            binding_sha256=stage_binding_sha256(binding_path),
            baseline_identifier="baseline",
            process_version="process",
            code_version="code",
            state=StageBindingApprovalState.APPROVED,
            approved_at=NOW - timedelta(minutes=1),
            effective_at=NOW,
            expires_at=NOW + timedelta(days=1),
            governance_identifier="governance:1",
            approver_role="operations_governance",
            approved_modules=("some_other_module",),
            required_secret_names=(),
            rationale="invalid module set",
        )
    )
    with pytest.raises(StageBindingApprovalError, match="unapproved command module"):
        require_approved_stage_bindings(
            binding_path,
            approval_database=store.path,
            baseline_identifier="baseline",
            process_version="process",
            code_version="code",
            evaluated_at=NOW,
            environ={},
        )


def test_stage_binding_approval_history_is_append_only(tmp_path: Path) -> None:
    binding_path = _bindings(tmp_path / "bindings.json")
    store = SQLiteStageBindingApprovalStore(tmp_path / "approvals.db")
    approval = _approval(binding_path)
    assert store.append(approval) == 1
    assert store.append(approval) == 1
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM stage_binding_approval_events")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE stage_binding_approval_events SET payload_json='{}'"
            )
