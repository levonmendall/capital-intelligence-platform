from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import cio.persistence as persistence
import operations.bounded_cio_journal as bounded


class _NoFetchAllCursor:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __iter__(self):
        return iter(self._delegate)

    def fetchall(self):
        raise AssertionError("bounded journal reads must not call fetchall()")

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class _NoFetchAllConnection:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __enter__(self):
        self._delegate.__enter__()
        return self

    def __exit__(self, *args):
        return self._delegate.__exit__(*args)

    def execute(self, *args, **kwargs):
        return _NoFetchAllCursor(self._delegate.execute(*args, **kwargs))

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


def _append(
    journal: persistence.SQLiteCIOJournal,
    *,
    event_type: persistence.CIOJournalEventType,
    aggregate: str,
    occurred_at: datetime,
    payload: dict,
    suffix: str,
) -> None:
    journal.append(
        event_type=event_type,
        aggregate_identifier=aggregate,
        occurred_at=occurred_at,
        payload=payload,
        schema_version="test.v1",
        event_identifier=f"event:test:{suffix}",
    )


def _candidate(identifier: str = "candidate:current", symbol: str = "AAA"):
    return SimpleNamespace(
        identifier=identifier,
        instrument=SimpleNamespace(
            instrument_id="instrument:aaa",
            symbol=symbol,
        ),
    )


def _thesis_payload(
    *,
    identifier: str,
    episode: str,
    state: persistence.ThesisState,
    asset: str,
    created_at: datetime,
    updated_at: datetime,
) -> dict:
    return {
        "identifier": identifier,
        "decision_identifier": f"decision:{identifier}",
        "candidate_identifier": "candidate:historical",
        "asset": asset,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "state": state.value,
        "original_rationale": "governed thesis",
        "assumptions": ["assumption"],
        "expected_return": 0.10,
        "expected_downside": -0.05,
        "horizon_days": 30,
        "catalysts": ["catalyst"],
        "invalidation_conditions": ["invalidation"],
        "monitoring_indicators": ["indicator"],
        "initial_confidence": 0.60,
        "current_confidence": 0.65,
        "evidence_identifiers": ["evidence:1"],
        "performance_since_approval": 0.01,
        "next_review_at": (updated_at + timedelta(days=1)).isoformat(),
        "review_count": 1,
        "ownership_episode_identifier": episode,
    }


def test_integrity_streams_complete_journal_without_fetchall(tmp_path):
    journal = persistence.SQLiteCIOJournal(tmp_path / "journal.db")
    base = datetime(2026, 8, 20, tzinfo=timezone.utc)
    large_irrelevant = "x" * (64 * 1024)
    for index in range(64):
        _append(
            journal,
            event_type=persistence.CIOJournalEventType.SPECIALIST_PACKET,
            aggregate=f"candidate:{index}",
            occurred_at=base + timedelta(seconds=index),
            payload={"candidate": index, "irrelevant": large_irrelevant},
            suffix=f"large:{index}",
        )

    original_connect = journal._connect
    journal._connect = lambda: _NoFetchAllConnection(original_connect())

    assert bounded._bounded_verify_integrity(journal) is True


def test_prior_decision_projection_matches_canonical_semantics_without_events(tmp_path):
    journal = persistence.SQLiteCIOJournal(tmp_path / "journal.db")
    base = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
    aggregate = "candidate:historical"
    candidate = _candidate()

    _append(
        journal,
        event_type=persistence.CIOJournalEventType.CANDIDATE_DECISION,
        aggregate=aggregate,
        occurred_at=base,
        payload={"instrument": {"instrument_id": "instrument:aaa"}},
        suffix="candidate",
    )
    decisions = (
        (
            base + timedelta(minutes=1),
            "decision:buy",
            persistence.CIOAction.BUY,
            {},
        ),
        (
            base + timedelta(minutes=2),
            "decision:deferred-reduce",
            persistence.CIOAction.REDUCE,
            {
                "hysteresis_applied": True,
                "deferred_action": persistence.CIOAction.HOLD.value,
            },
        ),
        (
            base + timedelta(minutes=3),
            "decision:hold",
            persistence.CIOAction.HOLD,
            {},
        ),
    )
    for index, (occurred_at, identifier, action, extra) in enumerate(decisions):
        _append(
            journal,
            event_type=persistence.CIOJournalEventType.CIO_DECISION,
            aggregate=aggregate,
            occurred_at=occurred_at,
            payload={
                "identifier": identifier,
                "action": action.value,
                "recommended_position_weight": 0.08,
                **extra,
            },
            suffix=f"decision:{index}",
        )
    _append(
        journal,
        event_type=persistence.CIOJournalEventType.THESIS_SNAPSHOT,
        aggregate="thesis:prior",
        occurred_at=base + timedelta(minutes=4),
        payload={"asset": "AAA", "state": persistence.ThesisState.STABLE.value},
        suffix="prior-thesis",
    )
    cutoff = base + timedelta(hours=1)

    expected = bounded._ORIGINAL_PRIOR_DECISION_CONTEXTS(
        journal,
        (candidate,),
        as_of=cutoff,
    )
    journal.events = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("bounded prior projection must not materialize journal events")
    )
    actual = bounded._bounded_prior_decision_contexts(
        journal,
        (candidate,),
        as_of=cutoff,
    )

    assert actual == expected
    assert actual[0].prior_action is persistence.CIOAction.HOLD
    assert actual[0].consecutive_supportive_cycles == 3
    assert actual[0].consecutive_opposing_cycles == 0
    assert actual[0].last_material_change_at == base + timedelta(minutes=2)
    assert actual[0].thesis_state is persistence.ThesisState.STABLE


def test_active_thesis_projection_matches_canonical_latest_episode_semantics(tmp_path):
    journal = persistence.SQLiteCIOJournal(tmp_path / "journal.db")
    base = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
    candidate = _candidate()

    _append(
        journal,
        event_type=persistence.CIOJournalEventType.THESIS_SNAPSHOT,
        aggregate="thesis:one",
        occurred_at=base + timedelta(minutes=1),
        payload=_thesis_payload(
            identifier="thesis:one",
            episode="ownership:one",
            state=persistence.ThesisState.ACTIVE,
            asset="AAA",
            created_at=base,
            updated_at=base + timedelta(minutes=1),
        ),
        suffix="thesis:one:active",
    )
    _append(
        journal,
        event_type=persistence.CIOJournalEventType.THESIS_SNAPSHOT,
        aggregate="thesis:one",
        occurred_at=base + timedelta(minutes=2),
        payload={
            "identifier": "thesis:one",
            "asset": "AAA",
            "state": persistence.ThesisState.EXITED.value,
            "ownership_episode_identifier": "ownership:one",
        },
        suffix="thesis:one:exited",
    )
    _append(
        journal,
        event_type=persistence.CIOJournalEventType.THESIS_SNAPSHOT,
        aggregate="thesis:two",
        occurred_at=base + timedelta(minutes=3),
        payload=_thesis_payload(
            identifier="thesis:two",
            episode="ownership:two",
            state=persistence.ThesisState.STABLE,
            asset="AAA",
            created_at=base + timedelta(minutes=2),
            updated_at=base + timedelta(minutes=3),
        ),
        suffix="thesis:two:stable",
    )
    _append(
        journal,
        event_type=persistence.CIOJournalEventType.THESIS_SNAPSHOT,
        aggregate="thesis:irrelevant",
        occurred_at=base + timedelta(minutes=4),
        payload=_thesis_payload(
            identifier="thesis:irrelevant",
            episode="ownership:irrelevant",
            state=persistence.ThesisState.ACTIVE,
            asset="BBB",
            created_at=base + timedelta(minutes=3),
            updated_at=base + timedelta(minutes=4),
        ),
        suffix="thesis:irrelevant",
    )
    cutoff = base + timedelta(hours=1)

    expected = bounded._ORIGINAL_ACTIVE_THESES(
        journal,
        (candidate,),
        as_of=cutoff,
    )
    journal.events = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("bounded active-thesis projection must not materialize events")
    )
    actual = bounded._bounded_active_theses(
        journal,
        (candidate,),
        as_of=cutoff,
    )

    assert actual == expected
    assert tuple(item.identifier for item in actual) == ("thesis:two",)


def test_installer_is_idempotent_and_replaces_only_journal_read_methods():
    journal_type = persistence.SQLiteCIOJournal
    current = (
        journal_type.verify_integrity,
        journal_type.prior_decision_contexts,
        journal_type.active_theses,
    )
    try:
        if current != (
            bounded._ORIGINAL_VERIFY_INTEGRITY,
            bounded._ORIGINAL_PRIOR_DECISION_CONTEXTS,
            bounded._ORIGINAL_ACTIVE_THESES,
        ):
            journal_type.verify_integrity = bounded._ORIGINAL_VERIFY_INTEGRITY
            journal_type.prior_decision_contexts = bounded._ORIGINAL_PRIOR_DECISION_CONTEXTS
            journal_type.active_theses = bounded._ORIGINAL_ACTIVE_THESES
        bounded.install_bounded_cio_journal_reads()
        bounded.install_bounded_cio_journal_reads()
        assert journal_type.verify_integrity is bounded._bounded_verify_integrity
        assert (
            journal_type.prior_decision_contexts
            is bounded._bounded_prior_decision_contexts
        )
        assert journal_type.active_theses is bounded._bounded_active_theses
    finally:
        journal_type.verify_integrity = current[0]
        journal_type.prior_decision_contexts = current[1]
        journal_type.active_theses = current[2]
