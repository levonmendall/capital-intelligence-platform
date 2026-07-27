"""Tests for fail-closed readiness assembly from persisted authorities."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from governance import (
    AssetClassApproval,
    AssetClassApprovalState,
    AssetClassCapabilityProfile,
    CustodySettlementModel,
    OperationalReadinessSnapshot,
    ProductTestReadiness,
    ProductTestReadinessEvidenceAssembler,
    ProductTestReadinessEvaluator,
    ReadinessGate,
    ReadinessGateCertification,
    ReadinessGateState,
    SQLiteAssetClassApprovalStore,
    SQLiteReadinessEvidenceStore,
    TradingSessionModel,
)
from run_test_readiness import main as readiness_main

UTC = timezone.utc
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=UTC)
BASELINE = "test-baseline:multi-asset-alpha.1"
PROCESS = "capital-intelligence-investment-process.v1-test"
CODE = "commit:test-ready"


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
    effective = effective_at or (NOW - timedelta(days=1))
    return ReadinessGateCertification(
        identifier=f"readiness-gate:{gate.value}:{state.value}:{effective.isoformat()}",
        gate=gate,
        state=state,
        certified_at=effective - timedelta(hours=1),
        effective_at=effective,
        expires_at=expires_at or (NOW + timedelta(days=30)),
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        evidence_identifiers=(f"evidence:{gate.value}",),
        authority_identifiers=(f"authority:{gate.value}",),
        limitations=("controlled paper test only",),
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
    observed = observed_at or (NOW - timedelta(minutes=10))
    return OperationalReadinessSnapshot(
        identifier=f"operational-readiness:{observed.isoformat()}",
        observed_at=observed,
        knowledge_cutoff=cutoff or observed,
        baseline_identifier=baseline,
        process_version=process,
        code_version=code,
        unresolved_critical_incidents=incidents,
        data_integrity_failures=data_failures,
        reconciliation_failures=reconciliation_failures,
        source_identifiers=("slo:daily", "incident-register:current"),
    )


def _profile(asset_class: CandidateAssetClass) -> AssetClassCapabilityProfile:
    if asset_class is CandidateAssetClass.CRYPTO:
        venues = ("COINBASE",)
        countries = ("GLOBAL",)
        session = TradingSessionModel.CONTINUOUS_24_7
        custody = CustodySettlementModel.QUALIFIED_DIGITAL_ASSET_CUSTODY
    elif asset_class is CandidateAssetClass.FX:
        venues = ("EBS",)
        countries = ("GLOBAL",)
        session = TradingSessionModel.CONTINUOUS_24_5
        custody = CustodySettlementModel.PRIME_BROKER_SPOT_FX
    elif asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        venues = ("LSE",)
        countries = ("GB",)
        session = TradingSessionModel.EXCHANGE_LOCAL
        custody = CustodySettlementModel.BROKER_CUSTODIED_SECURITY
    else:
        raise AssertionError("unsupported expansion asset class")
    prefix = asset_class.value
    return AssetClassCapabilityProfile(
        asset_class=asset_class,
        state=AssetClassApprovalState.PAPER_ELIGIBLE,
        approved_venues=venues,
        approved_country_codes=countries,
        base_currency="USD",
        supported_quote_currencies=("USD",),
        trading_session_model=session,
        custody_settlement_model=custody,
        identity_model_version=f"{prefix}.identity.v1",
        valuation_model_version=f"{prefix}.valuation.v1",
        expected_return_model_version=f"{prefix}.expected-return.v1",
        liquidity_model_version=f"{prefix}.liquidity.v1",
        cost_model_version=f"{prefix}.cost.v1",
        portfolio_risk_model_version=f"{prefix}.risk.v1",
        execution_model_version=f"{prefix}.execution.v1",
        thesis_model_version=f"{prefix}.thesis.v1",
        evaluation_model_version=f"{prefix}.evaluation.v1",
        security_master_certification_identifier=f"cert:{prefix}:security-master",
        market_data_certification_identifier=f"cert:{prefix}:market-data",
        analytical_evidence_certification_identifier=f"cert:{prefix}:evidence",
        execution_certification_identifier=f"cert:{prefix}:execution",
        custody_settlement_identifier=f"cert:{prefix}:custody",
        source_identifiers=(f"source:{prefix}:test-only",),
        limitations=("synthetic test-only approval",),
    )


def _approval(
    asset_class: CandidateAssetClass,
    *,
    process: str = PROCESS,
    code: str = CODE,
) -> AssetClassApproval:
    return AssetClassApproval(
        identifier=f"asset-approval:{asset_class.value}:test-only",
        profile=_profile(asset_class),
        approved_at=NOW - timedelta(days=2, hours=1),
        effective_at=NOW - timedelta(days=2),
        expires_at=NOW + timedelta(days=30),
        governance_identifier=f"governance:{asset_class.value}:test-only",
        process_version=process,
        code_version=code,
        rationale="Synthetic acceptance record; no production activation.",
    )


def _stores(tmp_path: Path):
    return (
        SQLiteReadinessEvidenceStore(tmp_path / "readiness-evidence.db"),
        SQLiteAssetClassApprovalStore(tmp_path / "asset-class.db"),
    )


def _append_all_gates(store: SQLiteReadinessEvidenceStore) -> None:
    for gate in ReadinessGate:
        store.append_gate(_gate(gate))


def _append_all_asset_approvals(store: SQLiteAssetClassApprovalStore) -> None:
    for asset_class in (
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FX,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
    ):
        store.append(_approval(asset_class))


def _assemble(
    evidence_store: SQLiteReadinessEvidenceStore,
    asset_store: SQLiteAssetClassApprovalStore,
    **overrides,
):
    values = {
        "assessed_at": NOW,
        "baseline_identifier": BASELINE,
        "process_version": PROCESS,
        "code_version": CODE,
        "open_development_items": ("continue post-baseline research on main",),
    }
    values.update(overrides)
    return ProductTestReadinessEvidenceAssembler(
        evidence_store=evidence_store,
        asset_class_store=asset_store,
    ).assemble(**values)


def test_empty_persisted_authorities_fail_closed_without_manual_booleans(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)

    evidence = _assemble(evidence_store, asset_store)
    report = ProductTestReadinessEvaluator().evaluate(evidence)

    assert report.state is ProductTestReadiness.DEVELOPMENT_IN_PROGRESS
    assert evidence.development_remains_open is True
    assert all(
        getattr(evidence, gate.value) is False for gate in ReadinessGate
    )
    assert "certification unavailable" in " ".join(
        evidence.open_development_items
    )
    assert report.real_money_authorized is False


def test_gate_certifications_cannot_substitute_for_asset_class_approvals(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    _append_all_gates(evidence_store)
    evidence_store.append_operational(_operational())

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.core_us_market_ready is True
    assert evidence.crypto_market_ready is False
    assert evidence.spot_fx_market_ready is False
    assert evidence.international_equity_market_ready is False
    assert any(
        "active asset-class approval unavailable" in item
        for item in evidence.open_development_items
    )


def test_complete_exact_persisted_baseline_can_be_ready_while_development_remains_open(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    _append_all_gates(evidence_store)
    _append_all_asset_approvals(asset_store)
    evidence_store.append_operational(_operational())

    evidence = _assemble(evidence_store, asset_store)
    report = ProductTestReadinessEvaluator().evaluate(evidence)

    assert report.state is ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST
    assert evidence.development_remains_open is True
    assert report.development_items == (
        "continue post-baseline research on main",
    )
    assert report.real_money_authorized is False
    assert report.performance_claims_permitted is False
    assert all(getattr(evidence, gate.value) is True for gate in ReadinessGate)
    assert any(item.startswith("asset-approval:crypto") for item in evidence.evidence_identifiers)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("baseline_identifier", "test-baseline:other", "baseline mismatch"),
        ("process_version", "investment-process:other", "process-version mismatch"),
        ("code_version", "commit:other", "code-version mismatch"),
    ),
)
def test_gate_version_mismatch_fails_exact_baseline(
    tmp_path: Path,
    field: str,
    value: str,
    expected: str,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    for gate in ReadinessGate:
        kwargs = {field.removesuffix("_identifier"): value} if field == "baseline_identifier" else {field.removesuffix("_version"): value}
        if gate is ReadinessGate.CERTIFIED_DATA:
            evidence_store.append_gate(_gate(gate, **kwargs))
        else:
            evidence_store.append_gate(_gate(gate))
    _append_all_asset_approvals(asset_store)
    evidence_store.append_operational(_operational())

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.certified_data_ready is False
    assert any(expected in item for item in evidence.open_development_items)


def test_latest_suspended_gate_supersedes_prior_satisfaction(tmp_path: Path) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    _append_all_gates(evidence_store)
    evidence_store.append_gate(
        _gate(
            ReadinessGate.PAPER_EXECUTION,
            state=ReadinessGateState.SUSPENDED,
            effective_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(days=1),
        )
    )
    _append_all_asset_approvals(asset_store)
    evidence_store.append_operational(_operational())

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.paper_execution_ready is False
    assert any(
        "paper_execution_ready: state=suspended" in item
        for item in evidence.open_development_items
    )


def test_stale_operational_snapshot_forces_operations_security_and_resilience_false(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    _append_all_gates(evidence_store)
    _append_all_asset_approvals(asset_store)
    old = NOW - timedelta(hours=25)
    evidence_store.append_operational(_operational(observed_at=old, cutoff=old))

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.daily_operations_ready is False
    assert evidence.security_suite_ready is False
    assert evidence.resilience_campaign_ready is False
    assert "operational readiness snapshot is stale" in evidence.open_development_items


def test_incidents_integrity_and_reconciliation_failures_block_relevant_gates(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    _append_all_gates(evidence_store)
    _append_all_asset_approvals(asset_store)
    evidence_store.append_operational(
        _operational(
            incidents=1,
            data_failures=2,
            reconciliation_failures=3,
        )
    )

    evidence = _assemble(evidence_store, asset_store)
    report = ProductTestReadinessEvaluator().evaluate(evidence)

    assert evidence.daily_operations_ready is False
    assert evidence.security_suite_ready is False
    assert evidence.resilience_campaign_ready is False
    assert report.state is ProductTestReadiness.DEVELOPMENT_IN_PROGRESS
    assert set(report.blockers) >= {
        "daily_operations",
        "security_suite",
        "resilience_campaign",
        "unresolved_critical_incidents",
        "data_integrity_failures",
        "reconciliation_failures",
    }


def test_asset_approval_process_or_code_mismatch_blocks_only_that_market(
    tmp_path: Path,
) -> None:
    evidence_store, asset_store = _stores(tmp_path)
    _append_all_gates(evidence_store)
    asset_store.append(_approval(CandidateAssetClass.CRYPTO, code="commit:wrong"))
    asset_store.append(_approval(CandidateAssetClass.FX))
    asset_store.append(_approval(CandidateAssetClass.INTERNATIONAL_EQUITY))
    evidence_store.append_operational(_operational())

    evidence = _assemble(evidence_store, asset_store)

    assert evidence.crypto_market_ready is False
    assert evidence.spot_fx_market_ready is True
    assert evidence.international_equity_market_ready is True
    assert any(
        "crypto_market_ready: asset approval code mismatch" in item
        for item in evidence.open_development_items
    )


def test_readiness_evidence_store_is_idempotent_append_only_and_tamper_evident(
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


def test_readiness_cli_uses_persisted_authorities_by_default(
    tmp_path: Path,
    capsys,
) -> None:
    evidence_store = SQLiteReadinessEvidenceStore(tmp_path / "evidence.db")
    asset_store = SQLiteAssetClassApprovalStore(tmp_path / "assets.db")
    _append_all_gates(evidence_store)
    _append_all_asset_approvals(asset_store)
    evidence_store.append_operational(_operational())

    exit_code = readiness_main(
        (
            "--baseline-identifier",
            BASELINE,
            "--process-version",
            PROCESS,
            "--code-version",
            CODE,
            "--assessed-at",
            NOW.isoformat(),
            "--readiness-evidence-database",
            str(evidence_store.path),
            "--asset-class-governance-database",
            str(asset_store.path),
            "--database",
            str(tmp_path / "reports.db"),
            "--development-item",
            "continue development on later commits",
            "--require-ready",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["state"] == ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST.value
    assert output["evidence_source"] == "persisted_authorities"
    assert output["development_remains_open"] is True
    assert output["real_money_authorized"] is False


def test_manual_evidence_remains_explicit_compatibility_mode(
    tmp_path: Path,
    capsys,
) -> None:
    payload = {
        "identifier": "manual:compatibility",
        "assessed_at": NOW.isoformat(),
        "test_baseline_identifier": BASELINE,
        "process_version": PROCESS,
        "code_version": CODE,
        "development_remains_open": True,
        **{gate.value: False for gate in ReadinessGate},
        "unresolved_critical_incidents": 0,
        "data_integrity_failures": 0,
        "reconciliation_failures": 0,
        "evidence_identifiers": ["manual:caller-assertion"],
        "open_development_items": ["manual evidence is noncanonical"],
    }
    path = tmp_path / "manual.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = readiness_main(
        (
            "--manual-evidence",
            str(path),
            "--database",
            str(tmp_path / "manual-reports.db"),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["evidence_source"] == "manual_compatibility"
    assert output["state"] == ProductTestReadiness.DEVELOPMENT_IN_PROGRESS.value
