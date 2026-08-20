from __future__ import annotations

from datetime import datetime, timezone

import pytest

import cio.persistence as persistence
import operations.bounded_cio_journal as bounded
import operations.streaming_cio_journal_integrity as streaming


def _append_large_packet(journal: persistence.SQLiteCIOJournal) -> None:
    journal.append(
        event_type=persistence.CIOJournalEventType.SPECIALIST_PACKET,
        aggregate_identifier="candidate:large-packet",
        occurred_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        payload={
            "candidate_identifier": "candidate:large-packet",
            "nested": {
                "blob": "x" * (4 * 1024 * 1024),
                "values": [True, False, None, -12.5, 3.2e4],
                "escaped": "line\\nquote\\\"unicode\\u0041",
            },
        },
        schema_version="specialist-packet.test.v1",
        event_identifier="event:test:large-specialist-packet",
    )


def test_streaming_validator_accepts_nested_object_without_materializing_values() -> None:
    streaming.validate_json_object_text(
        '{"a":[1,-2.5e+3,true,false,null,{"b":"x\\n\\u0041"}],"c":{}}'
    )


@pytest.mark.parametrize(
    "payload",
    (
        "[]",
        '{"a":1} trailing',
        '{"a":01}',
        '{"a":"unterminated}',
        '{"a":[1,2,]}',
        '{"a":tru}',
    ),
)
def test_streaming_validator_rejects_invalid_or_non_object_payload(payload: str) -> None:
    with pytest.raises(ValueError):
        streaming.validate_json_object_text(payload)


def test_event_append_never_full_decodes_large_payload(monkeypatch, tmp_path) -> None:
    event_type = persistence.CIOJournalEvent
    previous_post_init = event_type.__post_init__
    try:
        event_type.__post_init__ = streaming._ORIGINAL_CIO_JOURNAL_EVENT_POST_INIT
        streaming.install_streaming_cio_journal_event_validation()
        monkeypatch.setattr(
            persistence.json,
            "loads",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("journal append must not json.loads a complete payload")
            ),
        )

        journal = persistence.SQLiteCIOJournal(tmp_path / "journal.db")
        _append_large_packet(journal)
    finally:
        event_type.__post_init__ = previous_post_init


def test_streaming_event_validation_preserves_non_object_contract() -> None:
    event_type = persistence.CIOJournalEvent
    previous_post_init = event_type.__post_init__
    try:
        event_type.__post_init__ = streaming._ORIGINAL_CIO_JOURNAL_EVENT_POST_INIT
        streaming.install_streaming_cio_journal_event_validation()
        with pytest.raises(ValueError, match="payload_json must encode an object"):
            event_type(
                sequence=1,
                event_identifier="event:test:non-object",
                aggregate_identifier="candidate:test",
                event_type=persistence.CIOJournalEventType.SPECIALIST_PACKET,
                occurred_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                recorded_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                schema_version="specialist-packet.test.v1",
                payload_json="[]",
                previous_hash="genesis",
                content_hash="content",
            )
    finally:
        event_type.__post_init__ = previous_post_init


def test_integrity_scan_never_full_decodes_large_payload(monkeypatch, tmp_path) -> None:
    journal = persistence.SQLiteCIOJournal(tmp_path / "journal.db")
    _append_large_packet(journal)

    monkeypatch.setattr(
        bounded.json,
        "loads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("integrity verification must not json.loads a complete payload")
        ),
    )

    assert streaming._streaming_verify_integrity(journal) is True


def test_streaming_installer_composes_with_bounded_journal_installer() -> None:
    event_type = persistence.CIOJournalEvent
    journal_type = persistence.SQLiteCIOJournal
    previous_event_post_init = event_type.__post_init__
    previous_projection = bounded._bounded_verify_integrity
    previous_methods = (
        journal_type.verify_integrity,
        journal_type.prior_decision_contexts,
        journal_type.active_theses,
    )
    try:
        event_type.__post_init__ = streaming._ORIGINAL_CIO_JOURNAL_EVENT_POST_INIT
        bounded._bounded_verify_integrity = streaming._ORIGINAL_BOUNDED_VERIFY_INTEGRITY
        journal_type.verify_integrity = bounded._ORIGINAL_VERIFY_INTEGRITY
        journal_type.prior_decision_contexts = bounded._ORIGINAL_PRIOR_DECISION_CONTEXTS
        journal_type.active_theses = bounded._ORIGINAL_ACTIVE_THESES

        streaming.install_streaming_cio_journal_integrity()
        bounded.install_bounded_cio_journal_reads()
        streaming.install_streaming_cio_journal_integrity()

        assert event_type.__post_init__ is streaming._streaming_event_post_init
        assert bounded._bounded_verify_integrity is streaming._streaming_verify_integrity
        assert journal_type.verify_integrity is streaming._streaming_verify_integrity
        assert journal_type.prior_decision_contexts is bounded._bounded_prior_decision_contexts
        assert journal_type.active_theses is bounded._bounded_active_theses
    finally:
        event_type.__post_init__ = previous_event_post_init
        bounded._bounded_verify_integrity = previous_projection
        journal_type.verify_integrity = previous_methods[0]
        journal_type.prior_decision_contexts = previous_methods[1]
        journal_type.active_theses = previous_methods[2]
