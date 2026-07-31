from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.config import ApiSettings
from api.routes.health import _composite_report
from governance import OperationalReadinessSnapshot, SQLiteReadinessEvidenceStore
from operations.config import OperationalSettings
from operations.composite_readiness import (
    CompositeReadinessPolicy,
    assess_composite_readiness,
    component_heartbeat_path,
)
from operations.heartbeat import WorkerHeartbeatStore
from run_composite_readiness_watchdog import run_watchdog


NOW = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)
SHA = "a" * 40
COMPONENTS = {
    "api": 120,
    "streamlit": 120,
    "cio-paper-operator": 120,
    "historical-backfill": 172800,
    "encrypted-backup": 172800,
}


def _policy() -> CompositeReadinessPolicy:
    return CompositeReadinessPolicy(
        component_maximum_age_seconds=COMPONENTS,
        data_maximum_age_seconds=120,
        backup_maximum_age_seconds=172800,
    )


def _write_all(root, *, at=NOW) -> None:
    for name in COMPONENTS:
        WorkerHeartbeatStore(component_heartbeat_path(root, name)).write(
            "healthy",
            observed_at=at,
        )


def test_complete_production_readiness_reports_release_and_every_gate(tmp_path) -> None:
    _write_all(tmp_path)
    report = assess_composite_readiness(
        state_root=tmp_path,
        deployed_git_sha=SHA,
        reconciliation_ready=True,
        policy=_policy(),
        now=NOW,
    )

    assert report.ready is True
    assert report.deployed_git_sha == SHA
    assert {
        "api",
        "streamlit",
        "cio-paper-operator",
        "historical-backfill",
        "encrypted-backup",
        "data_freshness",
        "backup_age",
        "reconciliation",
        "deployed_git_sha",
    } == set(report.components)
    assert report.to_dict()["real_money_authorized"] is False


def test_missing_stale_failed_or_future_heartbeat_blocks(tmp_path) -> None:
    _write_all(tmp_path)
    WorkerHeartbeatStore(component_heartbeat_path(tmp_path, "api")).write(
        "healthy",
        observed_at=NOW - timedelta(seconds=121),
    )
    report = assess_composite_readiness(
        state_root=tmp_path,
        deployed_git_sha=SHA,
        reconciliation_ready=True,
        policy=_policy(),
        now=NOW,
    )
    assert report.ready is False
    assert report.components["api"]["ready"] is False


def test_reconciliation_backup_age_and_exact_sha_fail_closed(tmp_path) -> None:
    _write_all(tmp_path, at=NOW - timedelta(days=3))
    report = assess_composite_readiness(
        state_root=tmp_path,
        deployed_git_sha="unknown",
        reconciliation_ready=False,
        policy=_policy(),
        now=NOW,
    )
    assert report.ready is False
    assert report.components["backup_age"]["ready"] is False
    assert report.components["reconciliation"]["ready"] is False
    assert report.components["deployed_git_sha"]["ready"] is False


def test_watchdog_allows_startup_then_fails_after_sustained_block() -> None:
    values = iter((False, False, True, False, False))
    clock_value = [0.0]

    def sleep(seconds: float) -> None:
        clock_value[0] += seconds

    result = run_watchdog(
        probe=lambda: next(values),
        startup_grace_seconds=30,
        poll_seconds=5,
        consecutive_failures=2,
        clock=lambda: clock_value[0],
        sleeper=sleep,
    )
    assert result == 1


def test_api_composite_report_uses_persisted_reconciliation_evidence(tmp_path) -> None:
    _write_all(tmp_path, at=datetime.now(timezone.utc))
    evidence_path = tmp_path / "readiness.db"
    SQLiteReadinessEvidenceStore(evidence_path).append_operational(
        OperationalReadinessSnapshot(
            identifier="operational:ready",
            baseline_identifier="baseline:1",
            observed_at=NOW,
            knowledge_cutoff=NOW,
            process_version="process:1",
            code_version=SHA,
            unresolved_critical_incidents=0,
            data_integrity_failures=0,
            reconciliation_failures=0,
            source_identifiers=("reconciliation:ready",),
        )
    )
    settings = ApiSettings(
        portfolio_database=tmp_path / "canonical_portfolio.db",
        readiness_evidence_database=evidence_path,
        product_test_readiness_database=tmp_path / "paper-readiness.db",
    )
    operations = OperationalSettings(
        environment="production",
        release=SHA,
        enforce_https=True,
        metrics_token="m" * 32,
        require_encrypted_backups=True,
        backup_encryption_key="configured-by-render",
        require_operational_slos=True,
        backup_directory=tmp_path / "backups",
    )

    report = _composite_report(settings=settings, operations=operations)
    assert report["ready"] is True
    assert report["deployed_git_sha"] == SHA
