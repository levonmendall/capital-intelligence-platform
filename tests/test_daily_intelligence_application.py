"""End-to-end tests for the canonical daily intelligence experience."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from application import (
    DailyCapitalIntelligenceService,
    DailyIntelligenceStatus,
    SQLiteDailySnapshotStore,
    build_daily_capital_intelligence_snapshot,
    daily_snapshot_to_dict,
)
from committee import RegimeGovernanceWorkflow
from dashboard.daily_intelligence import build_daily_intelligence_view
from intelligence.regime_pipeline import InstitutionalRegimePipeline
from monitoring import RegimeMaterialChangeEngine
from tests.test_material_change_monitoring import (
    ChangedRegimeProvider,
    FIRST_AS_OF,
    SECOND_AS_OF,
    _decision,
    _run,
)


def _service(provider, *, store=None, clock=None):
    return DailyCapitalIntelligenceService(
        InstitutionalRegimePipeline(provider),
        governance=RegimeGovernanceWorkflow(
            clock=clock or (lambda: FIRST_AS_OF)
        ),
        change_engine=RegimeMaterialChangeEngine(
            clock=clock or (lambda: FIRST_AS_OF)
        ),
        store=store,
        clock=clock or (lambda: FIRST_AS_OF),
    )


def test_one_run_builds_every_opening_surface_from_the_same_sources(
    tmp_path,
) -> None:
    store = SQLiteDailySnapshotStore(tmp_path / "daily.db")
    service = _service(ChangedRegimeProvider(), store=store)

    cycle = service.run(
        as_of=FIRST_AS_OF,
        replay_identifiers=("decision-replay:1",),
    )
    snapshot = cycle.snapshot
    payload = daily_snapshot_to_dict(snapshot)

    assert snapshot.score.score == 82
    assert snapshot.score.environment == "Constructive"
    assert snapshot.score.risk == "Moderate"
    assert snapshot.environment.as_of == cycle.run.as_of
    assert snapshot.decision_card.as_of == cycle.run.as_of
    assert (
        payload["sources"]["regime_run"]
        == cycle.decision.regime_run_identifier
    )
    assert (
        payload["sources"]["decision"]
        == cycle.decision.decision_identifier
    )
    assert payload["decision_replays"] == ["decision-replay:1"]
    assert store.count() == 1


def test_snapshot_history_calculates_score_delta_without_duplicates(
    tmp_path,
) -> None:
    store = SQLiteDailySnapshotStore(tmp_path / "daily.db")
    first = _service(ChangedRegimeProvider(), store=store)
    first_cycle = first.run(as_of=FIRST_AS_OF)

    second = DailyCapitalIntelligenceService(
        InstitutionalRegimePipeline(
            ChangedRegimeProvider(current_date=date(2026, 1, 28))
        ),
        governance=RegimeGovernanceWorkflow(
            clock=lambda: SECOND_AS_OF
        ),
        change_engine=RegimeMaterialChangeEngine(
            clock=lambda: SECOND_AS_OF
        ),
        store=store,
        clock=lambda: SECOND_AS_OF,
    )
    second_cycle = second.run(
        as_of=SECOND_AS_OF,
        previous_run=first_cycle.run,
        previous_decision=first_cycle.decision,
    )

    assert second_cycle.snapshot.score_delta == 0
    assert second_cycle.snapshot.change_summary == (
        "The market view is unchanged. Keep the portfolio as it is."
    )
    assert store.count() == 2
    store.append(second_cycle.snapshot)
    assert store.count() == 2
    assert [item.as_of for item in store.history()] == [
        SECOND_AS_OF,
        FIRST_AS_OF,
    ]


def test_material_change_is_visible_and_uses_existing_alert_policy(
    tmp_path,
) -> None:
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    previous_decision = _decision(previous)
    service = DailyCapitalIntelligenceService(
        InstitutionalRegimePipeline(
            ChangedRegimeProvider(
                growth_value=95.0,
                current_date=date(2026, 1, 28),
            )
        ),
        governance=RegimeGovernanceWorkflow(
            clock=lambda: SECOND_AS_OF
        ),
        change_engine=RegimeMaterialChangeEngine(
            clock=lambda: SECOND_AS_OF
        ),
        store=SQLiteDailySnapshotStore(tmp_path / "daily.db"),
        clock=lambda: SECOND_AS_OF,
    )

    cycle = service.run(
        as_of=SECOND_AS_OF,
        previous_run=previous,
        previous_decision=previous_decision,
    )

    assert cycle.snapshot.changed_materially
    assert cycle.snapshot.should_alert
    assert cycle.snapshot.environment.headline == "Risk review is urgent"
    assert (
        cycle.snapshot.change_summary
        == cycle.change_assessment.explanation
    )


def test_operating_status_discloses_incomplete_stale_unavailable() -> None:
    incomplete = _run(
        ChangedRegimeProvider(unavailable={"WALCL", "STLFSI4"}),
        as_of=FIRST_AS_OF,
    )
    incomplete_snapshot = build_daily_capital_intelligence_snapshot(
        incomplete,
        _decision(incomplete),
        generated_at=FIRST_AS_OF,
    )
    assert (
        incomplete_snapshot.status
        is DailyIntelligenceStatus.INCOMPLETE
    )

    complete = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    stale_snapshot = build_daily_capital_intelligence_snapshot(
        complete,
        _decision(complete),
        generated_at=FIRST_AS_OF + timedelta(days=2),
    )
    assert stale_snapshot.status is DailyIntelligenceStatus.STALE

    unavailable = _run(
        ChangedRegimeProvider(
            unavailable={
                "INDPRO",
                "CPIAUCSL",
                "FEDFUNDS",
                "WALCL",
                "STLFSI4",
            }
        ),
        as_of=FIRST_AS_OF,
    )
    unavailable_snapshot = build_daily_capital_intelligence_snapshot(
        unavailable,
        _decision(unavailable),
        generated_at=FIRST_AS_OF,
    )
    assert (
        unavailable_snapshot.status
        is DailyIntelligenceStatus.UNAVAILABLE
    )


def test_history_store_is_append_only(tmp_path) -> None:
    store = SQLiteDailySnapshotStore(tmp_path / "daily.db")
    snapshot = _service(
        ChangedRegimeProvider(),
        store=store,
    ).run(as_of=FIRST_AS_OF).snapshot

    connection = sqlite3.connect(store.path)
    try:
        try:
            connection.execute(
                """
                UPDATE daily_intelligence_snapshots
                SET score = 1
                WHERE identifier = ?
                """,
                (snapshot.identifier,),
            )
        except sqlite3.IntegrityError as error:
            assert "append-only" in str(error)
        else:
            raise AssertionError("snapshot history allowed an update")
    finally:
        connection.close()


def test_daily_view_keeps_the_primary_surface_simple(tmp_path) -> None:
    store = SQLiteDailySnapshotStore(tmp_path / "daily.db")
    snapshot = _service(
        ChangedRegimeProvider(),
        store=store,
    ).run(
        as_of=FIRST_AS_OF,
        replay_identifiers=("decision-replay:decision-1",),
    ).snapshot

    view = build_daily_intelligence_view(
        snapshot,
        store.history(),
    )

    assert view.score == 82
    assert view.score_label == "Strong"
    assert view.score_change == "No prior score"
    assert view.environment == "Constructive"
    assert view.risk == "Moderate"
    assert view.committee == "6–0 Favor Risk Assets"
    assert view.history == ((FIRST_AS_OF.isoformat(), 82),)
    assert view.replay_identifiers == (
        "decision-replay:decision-1",
    )


def test_daily_snapshot_schema_is_stable_json() -> None:
    run = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    snapshot = build_daily_capital_intelligence_snapshot(
        run,
        _decision(run),
        generated_at=FIRST_AS_OF,
    )

    payload = daily_snapshot_to_dict(snapshot)
    assert payload["schema_version"] == "daily-capital-intelligence.v1"
    assert payload["score"]["score"] == 82
    assert json.loads(json.dumps(payload)) == payload
