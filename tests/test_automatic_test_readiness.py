"""Tests for diagnostic readiness assembly under immediate paper-test access."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance import (
    OperationalReadinessSnapshot,
    ProductTestReadiness,
    ProductTestReadinessEvidence,
    ProductTestReadinessEvidenceAssembler,
    ProductTestReadinessEvaluator,
    ReadinessGate,
    ReadinessGateCertification,
    ReadinessGateState,
    SQLiteAssetClassApprovalStore,
    SQLiteReadinessEvidenceStore,
)
from run_test_readiness import main as readiness_main

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 1, 0, tzinfo=UTC)
BASELINE = "test-baseline:optional-lineage"
PROCESS = "investment-process:optional-lineage"
CODE = "commit:current-paper-test"


def _gate(
    gate: ReadinessGate,
    *,
    state: ReadinessGateState = ReadinessGateState.SATISFIED,
    baseline: str = BASELINE,
    process: str = PROCESS,
    code: str = CODE,
    effective_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> ReadinessGateCertification:
    effective = effective_at or (NOW - timedelta(hours=1))
    return ReadinessGateCertification(
        identifier=(
            f"readiness-gate:{gate.value}:{state.value}:"
            f"{effective.isoformat()}:{baseline}:{process}:{code}"
        ),
        gate=gate,
        state=state,
        certified_at=effective - timedelta(minutes=1),
        effective_at=effective,
        expires_at=expires_at or (NOW + timedelta(days=1)),
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        evidence_identifiers=(f"evidence:{gate.value}",),
        authority_identifiers=(f"authority:{gate.value}",),
        limitations=("paper test only",),
    )


def _operational(
    *,
    observed_at: datetime | None = None,
    cutoff: datetime | None = None,
    baseline: str = BASELINE,
    process: str = PROCESS,
    code: str = CODE,
    incidents: int = 0,
    data_failures: int = 0,
    reconciliation_failures: int = 0,
) -> OperationalReadinessSnapshot:
    observed = observed_at or (NOW - timedelta(minutes=5))
    return OperationalReadinessSnapshot(
        identifier=f"operational-readiness:{observed.isoformat()}:{code}",
        observed_at=observed,
        knowledge_cutoff=cutoff or observed,
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        unresolved_critical_incidents=incidents,
        data_integrity_failures=data_failures,
        reconciliation_failures=reconciliation_failures,
        source_identifiers=("slo:current", "reconciliation:current"),
    )


def _stores(tmp_path: Path):
    return (
        SQLiteReadinessEvidenceStore(tmp_path / "readiness-evidence.db"),
        SQLiteAssetClassApprovalStore(tmp_path / "asset-class.db"),
    )


def _assemble(
    evidence_store: SQLiteReadinessEvidenceStore,
    asset_store: SQLiteAssetClassApprovalStore,
    *,
    baseline: str | None = BASELINE,
    process: str | None = PROCESS,
    code: str = CODE,
):
    return ProductTestReadinessEvidenceAssembler(
        evidence_store=evidence_store,
        asset_class_store=asset_store,
    ).assemble(
        assessed_at=NOW,
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        open_development_items=("continue product development",),
    )


def test_empty_authorities_remain_diagnostically_incomplete(tmp_path: Path) -> None:
    evidence_store, asset_store = _stores(tmp_path)

    evidence = _assemble(evidence_store, asset_store, baseline=None, process=None)
    report = ProductTestReadinessEvaluator().evaluate(evidence)

    assert report.state is ProductTestReadiness.DEVELOPMENT_IN_PROGRESS
    assert evidence.certified_data_ready is False
    assert evidence.paper_execution_ready is False
    assert any(
        "certification unavailable" in item
        for item in evidence.open_development_items
    )
    assert "immutable_test_baseline" not in report.blockers
    assert "versioned_investment_process" not in report.blockers
    assert report.real_money_authorized is False


@pytest.mark.parametrize(
    ("baseline", "process"),
    (
        ("test-baseline:other", PROCESS),
        (BASELINE, "investment-process:other"),
        (None, None),
    ),
)
def test_baseline_and_process_lineage_are_optional_diagnostics(
    tmp_path: Path,
    baseline: str | None,
    process: str | None,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    evidence_store.append_gate(
        _gate(
            ReadinessGate.CERTIFIED_DATA,
            baseline="recorded-baseline",
            process="recorded-process",
        )
    )

    evidence = _assemble(
        evidence_store,
        asset_store,
        baseline=baseline,
        process=process,
    )

    assert evidence.certified_data_ready is True
    assert not any(
        "baseline mismatch" in item for item in evidence.open_development_items
    )
    assert not any(
        "process-version mismatch" in item
        for item in evidence.open_development_items
    )


def test_current_code_version_remains_required_for_technical_evidence(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    evidence_store.append_gate(
        _gate(ReadinessGate.CERTIFIED_DATA, code="commit:stale")
    )

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.certified_data_ready is False
    assert any(
        "code-version mismatch" in item for item in evidence.open_development_items
    )


def test_market_gate_does_not_substitute_for_instrument_approval(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    evidence_store.append_gate(_gate(ReadinessGate.CRYPTO_MARKET))

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.crypto_market_ready is False
    assert any(
        "active asset-class approval unavailable" in item
        for item in evidence.open_development_items
    )


def test_latest_suspended_gate_supersedes_prior_satisfaction(tmp_path: Path) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    evidence_store.append_gate(_gate(ReadinessGate.PAPER_EXECUTION))
    evidence_store.append_gate(
        _gate(
            ReadinessGate.PAPER_EXECUTION,
            state=ReadinessGateState.SUSPENDED,
            effective_at=NOW - timedelta(minutes=1),
        )
    )

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.paper_execution_ready is False
    assert any(
        "paper_execution_ready: state=suspended" in item
        for item in evidence.open_development_items
    )


def test_stale_operational_snapshot_is_reported_without_launch_clearance(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    old = NOW - timedelta(hours=25)
    evidence_store.append_operational(_operational(observed_at=old, cutoff=old))

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.daily_operations_ready is False
    assert evidence.security_suite_ready is False
    assert evidence.resilience_campaign_ready is False
    assert "operational readiness snapshot is stale" in evidence.open_development_items


def test_incident_integrity_and_reconciliation_failures_remain_blockers(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    for gate in (
        ReadinessGate.DAILY_OPERATIONS,
        ReadinessGate.SECURITY_SUITE,
        ReadinessGate.PAPER_ONLY_DISCLOSURES,
    ):
        evidence_store.append_gate(_gate(gate))
    evidence_store.append_operational(
        _operational(incidents=1, data_failures=2, reconciliation_failures=3)
    )

    evidence = _assemble(evidence_store, asset_store)
    report = ProductTestReadinessEvaluator().evaluate(evidence)

    assert evidence.daily_operations_ready is False
    assert evidence.security_suite_ready is False
    assert set(report.blockers) >= {
        "daily_operations",
        "security_suite",
        "unresolved_critical_incidents",
        "data_integrity_failures",
        "reconciliation_failures",
    }
    assert "resilience_campaign" not in report.blockers


def test_readiness_store_is_idempotent_append_only_and_tamper_evident(
    tmp_path: Path,
) -> None:
    evidence_store, _ = _stores(tmp_path)
    gate = _gate(ReadinessGate.CORE_US_MARKET)
    operational = _operational()

    assert evidence_store.append_gate(gate) == 1
    assert evidence_store.append_gate(gate) == 1
    assert evidence_store.append_operational(operational) == 2
    assert evidence_store.verify_integrity()

    with sqlite3.connect(evidence_store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE product_readiness_evidence_events "
                "SET payload_json='{}' WHERE sequence=1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM product_readiness_evidence_events")


def test_readiness_cli_reports_no_launch_clearance_in_manual_mode(
    tmp_path: Path,
    capsys,
) -> None:
    payload = {
        "identifier": "manual:diagnostic",
        "assessed_at": NOW.isoformat(),
        "test_baseline_identifier": None,
        "process_version": None,
        "code_version": CODE,
        "development_remains_open": True,
        **{gate.value: False for gate in ReadinessGate},
        "unresolved_critical_incidents": 0,
        "data_integrity_failures": 0,
        "reconciliation_failures": 0,
        "evidence_identifiers": ["manual:diagnostic"],
        "open_development_items": ["diagnostic evidence incomplete"],
    }
    evidence_path = tmp_path / "manual.json"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = readiness_main(
        (
            "--manual-evidence",
            str(evidence_path),
            "--database",
            str(tmp_path / "reports.db"),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["evidence_source"] == "manual_compatibility"
    assert output["paper_launch_report_identifier"] is None
    assert output["launch_clearance_required"] is False
    assert output["real_money_authorized"] is False
