"""Acceptance tests for real elapsed burn-in and controlled failure evidence."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from operations import (
    REQUIRED_FAILURE_SCENARIOS,
    BurnInDayRecord,
    FailureScenarioKind,
    FailureScenarioRecord,
    FailureScenarioStatus,
    PaperTestCampaignBaseline,
    PaperTestCampaignError,
    PaperTestCampaignEvaluator,
    PaperTestCampaignState,
    SQLitePaperTestCampaignStore,
)

UTC = timezone.utc
CREATED = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _baseline(
    *,
    identifier: str = "paper-baseline:alpha-1",
    code_version: str = "commit:alpha",
    required_days: int = 5,
) -> PaperTestCampaignBaseline:
    return PaperTestCampaignBaseline(
        identifier=identifier,
        created_at=CREATED,
        effective_date=date(2026, 7, 27),
        process_version="investment-process:alpha-1",
        code_version=code_version,
        operation_plan_hash="plan-hash:alpha",
        stage_bindings_hash="binding-hash:alpha",
        configuration_hash="configuration-hash:alpha",
        data_manifest_identifier="all-markets:data-readiness:v1",
        required_consecutive_days=required_days,
    )


def _day(
    baseline: PaperTestCampaignBaseline,
    day: date,
    *,
    identifier: str | None = None,
    recorded_at: datetime | None = None,
    completed: bool = True,
    reconciled: bool = True,
    no_action: bool = False,
    duplicate_alerts: int = 0,
    incidents: int = 0,
    integrity_failures: int = 0,
) -> BurnInDayRecord:
    resolved_recorded_at = recorded_at or (
        datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=23)
    )
    return BurnInDayRecord(
        identifier=identifier or f"burn-in-day:{baseline.identifier}:{day.isoformat()}",
        baseline_identifier=baseline.identifier,
        baseline_fingerprint=baseline.fingerprint,
        operation_date=day,
        recorded_at=resolved_recorded_at,
        operation_identifier=f"daily-operation:{day.isoformat()}",
        operation_status="completed" if completed else "failed",
        completed_stage_count=12 if completed else 7,
        stage_output_identifiers=tuple(
            f"stage-output:{day.isoformat()}:{index}" for index in range(12)
        ),
        decision_identifier=f"decision:{day.isoformat()}",
        portfolio_snapshot_identifier=f"portfolio:{day.isoformat()}",
        readiness_snapshot_identifier=f"readiness:{day.isoformat()}",
        backup_identifier=f"backup:{day.isoformat()}",
        reconciliation_passed=reconciled,
        no_action_day=no_action,
        implementation_identifiers=(
            () if no_action else (f"implementation:{day.isoformat()}",)
        ),
        duplicate_alert_count=duplicate_alerts,
        unresolved_critical_incidents=incidents,
        data_integrity_failures=integrity_failures,
        source_identifiers=(
            f"daily-operation:{day.isoformat()}",
            f"readiness:{day.isoformat()}",
            f"backup:{day.isoformat()}",
        ),
    )


def _scenario(
    baseline: PaperTestCampaignBaseline,
    kind: FailureScenarioKind,
    *,
    status: FailureScenarioStatus = FailureScenarioStatus.PASSED,
    recorded_at: datetime = CREATED + timedelta(days=7),
) -> FailureScenarioRecord:
    return FailureScenarioRecord(
        identifier=f"failure-scenario:{baseline.identifier}:{kind.value}:{status.value}",
        baseline_identifier=baseline.identifier,
        baseline_fingerprint=baseline.fingerprint,
        kind=kind,
        status=status,
        recorded_at=recorded_at,
        isolated_environment=True,
        production_mutation_count=0,
        expected_behavior=f"Expected fail-closed behavior for {kind.value}.",
        actual_behavior=f"Observed fail-closed behavior for {kind.value}.",
        detection_seconds=5,
        recovery_seconds=30,
        data_loss_seconds=0,
        evidence_identifiers=(
            f"evidence:{kind.value}:detection",
            f"evidence:{kind.value}:recovery",
            f"evidence:{kind.value}:reconciliation",
        ),
        error=None if status is FailureScenarioStatus.PASSED else "scenario failed",
    )


def test_campaign_requires_all_real_consecutive_days_and_scenarios() -> None:
    baseline = _baseline()
    start = baseline.effective_date
    days = tuple(_day(baseline, start + timedelta(days=index)) for index in range(5))
    scenarios = tuple(_scenario(baseline, kind) for kind in REQUIRED_FAILURE_SCENARIOS)

    report = PaperTestCampaignEvaluator().evaluate(
        baseline=baseline,
        days=days,
        scenarios=scenarios,
        evaluated_at=CREATED + timedelta(days=8),
    )

    assert report.state is PaperTestCampaignState.SATISFIED
    assert report.consecutive_day_count == 5
    assert report.credited_dates == tuple(item.operation_date for item in days)
    assert set(report.passed_scenarios) == set(REQUIRED_FAILURE_SCENARIOS)
    assert report.missing_scenarios == ()
    assert report.failed_scenarios == ()
    assert report.blockers == ()
    assert report.paper_test_authorized is False
    payload = report.to_dict()
    assert payload["campaign_requirements_satisfied"] is True
    assert payload["paper_test_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert payload["performance_claims_permitted"] is False


def test_elapsed_days_cannot_be_synthesized_or_duplicated(tmp_path: Path) -> None:
    store = SQLitePaperTestCampaignStore(tmp_path / "campaign.db")
    baseline = _baseline()
    store.append_baseline(baseline)
    first = _day(baseline, baseline.effective_date)
    store.append_day(first)

    with pytest.raises(PaperTestCampaignError, match="already contains evidence"):
        store.append_day(
            _day(
                baseline,
                baseline.effective_date,
                identifier="burn-in-day:duplicate-date",
            )
        )

    with pytest.raises(ValueError, match="future or synthetic"):
        _day(
            baseline,
            date(2026, 8, 10),
            recorded_at=datetime(2026, 8, 9, 23, 0, tzinfo=UTC),
        )


def test_baseline_drift_resets_campaign_evidence(tmp_path: Path) -> None:
    store = SQLitePaperTestCampaignStore(tmp_path / "campaign.db")
    baseline = _baseline()
    changed = _baseline(
        identifier="paper-baseline:alpha-2",
        code_version="commit:changed",
    )
    store.append_baseline(baseline)
    store.append_baseline(changed)
    old_day = _day(baseline, baseline.effective_date)
    store.append_day(old_day)

    drifted = BurnInDayRecord.from_dict(
        {
            **old_day.to_dict(),
            "identifier": "burn-in-day:wrong-fingerprint",
            "baseline_identifier": changed.identifier,
            "operation_date": "2026-07-28",
            "recorded_at": "2026-07-28T23:00:00+00:00",
        }
    )
    with pytest.raises(PaperTestCampaignError, match="fingerprint"):
        store.append_day(drifted)

    report = PaperTestCampaignEvaluator().evaluate(
        baseline=changed,
        days=store.days(changed.identifier),
        scenarios=store.scenarios(changed.identifier),
        evaluated_at=CREATED + timedelta(days=10),
    )
    assert report.consecutive_day_count == 0
    assert report.state is PaperTestCampaignState.IN_PROGRESS


def test_failed_operating_evidence_blocks_campaign() -> None:
    baseline = _baseline(required_days=1)
    bad_day = _day(
        baseline,
        baseline.effective_date,
        completed=False,
        reconciled=False,
        duplicate_alerts=1,
        incidents=1,
        integrity_failures=1,
    )
    scenarios = tuple(_scenario(baseline, kind) for kind in REQUIRED_FAILURE_SCENARIOS)

    report = PaperTestCampaignEvaluator().evaluate(
        baseline=baseline,
        days=(bad_day,),
        scenarios=scenarios,
        evaluated_at=CREATED + timedelta(days=8),
    )

    assert bad_day.creditable is False
    assert report.state is PaperTestCampaignState.BLOCKED
    assert report.consecutive_day_count == 0
    assert any("quality controls" in item for item in report.blockers)


def test_missing_or_failed_failure_scenario_prevents_satisfaction() -> None:
    baseline = _baseline(required_days=1)
    day = _day(baseline, baseline.effective_date)
    missing_kind = FailureScenarioKind.EVIDENCE_LINEAGE_RECONSTRUCTION
    failed_kind = FailureScenarioKind.ENCRYPTED_BACKUP_RESTORE
    scenarios = tuple(
        _scenario(
            baseline,
            kind,
            status=(
                FailureScenarioStatus.FAILED
                if kind is failed_kind
                else FailureScenarioStatus.PASSED
            ),
        )
        for kind in REQUIRED_FAILURE_SCENARIOS
        if kind is not missing_kind
    )

    report = PaperTestCampaignEvaluator().evaluate(
        baseline=baseline,
        days=(day,),
        scenarios=scenarios,
        evaluated_at=CREATED + timedelta(days=8),
    )

    assert report.state is PaperTestCampaignState.BLOCKED
    assert report.missing_scenarios == (missing_kind,)
    assert report.failed_scenarios == (failed_kind,)


def test_latest_scenario_outcome_controls_campaign_state() -> None:
    baseline = _baseline(required_days=1)
    kind = FailureScenarioKind.PROVIDER_OUTAGE
    first = _scenario(
        baseline,
        kind,
        status=FailureScenarioStatus.FAILED,
        recorded_at=CREATED + timedelta(days=2),
    )
    second = FailureScenarioRecord.from_dict(
        {
            **_scenario(
                baseline,
                kind,
                status=FailureScenarioStatus.PASSED,
                recorded_at=CREATED + timedelta(days=3),
            ).to_dict(),
            "identifier": "failure-scenario:provider-outage:retest",
        }
    )
    remaining = tuple(
        _scenario(baseline, item)
        for item in REQUIRED_FAILURE_SCENARIOS
        if item is not kind
    )

    report = PaperTestCampaignEvaluator().evaluate(
        baseline=baseline,
        days=(_day(baseline, baseline.effective_date),),
        scenarios=(first, second, *remaining),
        evaluated_at=CREATED + timedelta(days=8),
    )

    assert report.state is PaperTestCampaignState.SATISFIED
    assert kind in report.passed_scenarios
    assert kind not in report.failed_scenarios


def test_no_action_day_is_valid_but_cannot_contain_implementation() -> None:
    baseline = _baseline(required_days=1)
    value = _day(baseline, baseline.effective_date, no_action=True)
    assert value.creditable is True
    assert value.implementation_identifiers == ()

    with pytest.raises(ValueError, match="no-action day"):
        BurnInDayRecord.from_dict(
            {
                **value.to_dict(),
                "identifier": "burn-in-day:invalid-no-action",
                "implementation_identifiers": ["implementation:unexpected"],
            }
        )


def test_failed_scenario_cannot_masquerade_as_passed() -> None:
    baseline = _baseline()
    with pytest.raises(ValueError, match="isolated"):
        FailureScenarioRecord(
            identifier="scenario:not-isolated",
            baseline_identifier=baseline.identifier,
            baseline_fingerprint=baseline.fingerprint,
            kind=FailureScenarioKind.PROVIDER_OUTAGE,
            status=FailureScenarioStatus.PASSED,
            recorded_at=CREATED,
            isolated_environment=False,
            production_mutation_count=0,
            expected_behavior="Fail closed.",
            actual_behavior="Fail closed.",
            detection_seconds=1,
            recovery_seconds=1,
            data_loss_seconds=0,
            evidence_identifiers=("evidence:1",),
        )

    with pytest.raises(ValueError, match="cannot mutate production"):
        FailureScenarioRecord(
            identifier="scenario:mutated",
            baseline_identifier=baseline.identifier,
            baseline_fingerprint=baseline.fingerprint,
            kind=FailureScenarioKind.PROVIDER_OUTAGE,
            status=FailureScenarioStatus.PASSED,
            recorded_at=CREATED,
            isolated_environment=True,
            production_mutation_count=1,
            expected_behavior="Fail closed.",
            actual_behavior="Fail closed.",
            detection_seconds=1,
            recovery_seconds=1,
            data_loss_seconds=0,
            evidence_identifiers=("evidence:1",),
        )


def test_campaign_store_is_append_only_and_report_round_trips(tmp_path: Path) -> None:
    store = SQLitePaperTestCampaignStore(tmp_path / "campaign.db")
    baseline = _baseline(required_days=1)
    store.append_baseline(baseline)
    store.append_day(_day(baseline, baseline.effective_date))
    for kind in REQUIRED_FAILURE_SCENARIOS:
        store.append_scenario(_scenario(baseline, kind))
    report = PaperTestCampaignEvaluator().evaluate(
        baseline=baseline,
        days=store.days(baseline.identifier),
        scenarios=store.scenarios(baseline.identifier),
        evaluated_at=CREATED + timedelta(days=8),
    )
    store.append_report(report)

    assert store.reports(baseline.identifier) == (report,)
    assert store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM paper_test_campaign_events")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE paper_test_campaign_events SET payload_json='{}'"
            )
