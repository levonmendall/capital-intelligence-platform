"""Bound production CIO journal reads independently of append-only history size.

The canonical CIO journal remains complete, append-only, hash chained, and authoritative.
This module changes only the in-process read model used by production CIO workers:

* journal integrity is verified one SQLite row at a time;
* prior-decision continuity is projected into compact state for current instruments while
  historical candidate and decision rows are streamed;
* active theses retain only the latest active snapshot for a currently relevant ownership
  episode while thesis history is streamed.

No historical event is deleted, skipped for integrity, or made non-authoritative.  No
candidate, evidence, specialist conclusion, CIO policy, construction rule, execution rule,
or real-money authority is changed.  Journal growth may increase scan time, but it must not
increase the number of full historical event objects retained in process memory.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

import cio.persistence as persistence


_ORIGINAL_VERIFY_INTEGRITY = persistence.SQLiteCIOJournal.verify_integrity
_ORIGINAL_PRIOR_DECISION_CONTEXTS = persistence.SQLiteCIOJournal.prior_decision_contexts
_ORIGINAL_ACTIVE_THESES = persistence.SQLiteCIOJournal.active_theses


@dataclass(slots=True)
class _PriorProjection:
    prior_decision_identifier: str
    prior_action: persistence.CIOAction
    prior_target_weight: float | None
    decided_at: datetime
    consecutive_supportive_cycles: int
    consecutive_opposing_cycles: int
    last_material_change_at: datetime | None


def _json_object(payload_json: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(payload_json, str):
        raise TypeError(f"{field_name} must be a JSON string")
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"{field_name} must be valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{field_name} must encode an object")
    return payload


def _row_datetime(value: object, *, field_name: str) -> datetime:
    try:
        resolved = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an ISO datetime") from error
    return persistence._aware(resolved, field_name=field_name)


def _bounded_verify_integrity(self: persistence.SQLiteCIOJournal) -> bool:
    """Verify the complete append-only chain without materializing all journal rows."""

    previous_hash = self._GENESIS_HASH
    expected_sequence = 1
    with self._connect() as connection:
        cursor = connection.execute(
            "SELECT * FROM cio_journal_events ORDER BY sequence ASC"
        )
        for row in cursor:
            sequence = int(row["sequence"])
            if sequence != expected_sequence:
                raise persistence.CIOJournalIntegrityError(
                    "CIO journal sequence is not contiguous"
                )
            event_identifier = persistence._required_text(
                str(row["event_identifier"]), field_name="event_identifier"
            )
            aggregate_identifier = persistence._required_text(
                str(row["aggregate_identifier"]), field_name="aggregate_identifier"
            )
            event_type = persistence.CIOJournalEventType(str(row["event_type"]))
            occurred_at = _row_datetime(row["occurred_at"], field_name="occurred_at")
            recorded_at = _row_datetime(row["recorded_at"], field_name="recorded_at")
            schema_version = persistence._required_text(
                str(row["schema_version"]), field_name="schema_version"
            )
            payload_json = str(row["payload_json"])
            # Preserve the historical contract that every hashed payload is a valid JSON
            # object, but release the decoded object before advancing the SQLite cursor.
            decoded = _json_object(payload_json, field_name="payload_json")
            del decoded
            row_previous_hash = persistence._required_text(
                str(row["previous_hash"]), field_name="previous_hash"
            )
            content_hash = persistence._required_text(
                str(row["content_hash"]), field_name="content_hash"
            )
            if row_previous_hash != previous_hash:
                raise persistence.CIOJournalIntegrityError(
                    "CIO journal previous hash does not match"
                )
            expected_hash = self._content_hash(
                sequence=sequence,
                event_identifier=event_identifier,
                aggregate_identifier=aggregate_identifier,
                event_type=event_type,
                occurred_at=occurred_at,
                recorded_at=recorded_at,
                schema_version=schema_version,
                payload_json=payload_json,
                previous_hash=row_previous_hash,
            )
            if content_hash != expected_hash:
                raise persistence.CIOJournalIntegrityError(
                    "CIO journal content hash does not match"
                )
            previous_hash = content_hash
            expected_sequence += 1
    return True


def _continuity_action(payload: Mapping[str, Any]) -> persistence.CIOAction:
    deferred = payload.get("deferred_action")
    if payload.get("hysteresis_applied") is True and deferred:
        try:
            return persistence.CIOAction(str(deferred))
        except ValueError:
            pass
    return persistence.CIOAction(payload["action"])


def _bounded_prior_decision_contexts(
    self: persistence.SQLiteCIOJournal,
    candidates,
    *,
    as_of: datetime,
):
    """Project only current-instrument continuity while streaming historical decisions."""

    decision_time = persistence._aware(as_of, field_name="as_of")
    if not _bounded_verify_integrity(self):
        raise persistence.CIOJournalIntegrityError("CIO journal integrity is unavailable")

    candidates_by_instrument: dict[str, list[object]] = {}
    symbols: set[str] = set()
    for candidate in candidates:
        instrument_identifier = str(candidate.instrument.instrument_id)
        candidates_by_instrument.setdefault(instrument_identifier, []).append(candidate)
        symbols.add(str(candidate.instrument.symbol))
    if not candidates_by_instrument:
        return ()

    supportive = {
        persistence.CIOAction.BUY,
        persistence.CIOAction.INCREASE,
        persistence.CIOAction.HOLD,
        persistence.CIOAction.NO_MATERIAL_CHANGE,
    }
    opposing = {persistence.CIOAction.REDUCE, persistence.CIOAction.EXIT}
    material = {
        persistence.CIOAction.BUY,
        persistence.CIOAction.INCREASE,
        persistence.CIOAction.REDUCE,
        persistence.CIOAction.EXIT,
    }
    projections: dict[str, _PriorProjection] = {}

    # Resolve each decision's immutable candidate record inside SQLite instead of
    # retaining a historical candidate-id -> instrument-id map whose size would grow with
    # the journal. append_candidate makes that aggregate record unique in canonical use.
    decision_sql = """
        SELECT d.*,
               (
                   SELECT c.payload_json
                   FROM cio_journal_events AS c
                   WHERE c.aggregate_identifier = d.aggregate_identifier
                     AND c.event_type = ?
                   ORDER BY c.sequence ASC
                   LIMIT 1
               ) AS candidate_payload_json,
               (
                   SELECT c.occurred_at
                   FROM cio_journal_events AS c
                   WHERE c.aggregate_identifier = d.aggregate_identifier
                     AND c.event_type = ?
                   ORDER BY c.sequence ASC
                   LIMIT 1
               ) AS candidate_occurred_at
        FROM cio_journal_events AS d
        WHERE d.event_type = ?
        ORDER BY d.sequence ASC
    """
    candidate_type = persistence.CIOJournalEventType.CANDIDATE_DECISION.value
    decision_type = persistence.CIOJournalEventType.CIO_DECISION.value
    with self._connect() as connection:
        cursor = connection.execute(
            decision_sql,
            (candidate_type, candidate_type, decision_type),
        )
        for row in cursor:
            occurred_at = _row_datetime(row["occurred_at"], field_name="occurred_at")
            if occurred_at >= decision_time:
                continue
            candidate_payload_json = row["candidate_payload_json"]
            candidate_occurred_raw = row["candidate_occurred_at"]
            if candidate_payload_json is None or candidate_occurred_raw is None:
                continue
            candidate_occurred_at = _row_datetime(
                candidate_occurred_raw,
                field_name="candidate_occurred_at",
            )
            if candidate_occurred_at >= decision_time:
                continue
            candidate_payload = _json_object(
                str(candidate_payload_json), field_name="candidate_payload_json"
            )
            instrument_payload = candidate_payload.get("instrument")
            if not isinstance(instrument_payload, Mapping):
                continue
            instrument_identifier = str(instrument_payload.get("instrument_id") or "")
            del candidate_payload
            if instrument_identifier not in candidates_by_instrument:
                continue

            payload = _json_object(str(row["payload_json"]), field_name="payload_json")
            action = persistence.CIOAction(payload["action"])
            continuity = _continuity_action(payload)
            previous = projections.get(instrument_identifier)
            if continuity in supportive:
                supportive_cycles = (
                    previous.consecutive_supportive_cycles + 1
                    if previous is not None
                    and previous.consecutive_supportive_cycles > 0
                    else 1
                )
                opposing_cycles = 0
            elif continuity in opposing:
                opposing_cycles = (
                    previous.consecutive_opposing_cycles + 1
                    if previous is not None
                    and previous.consecutive_opposing_cycles > 0
                    else 1
                )
                supportive_cycles = 0
            else:
                supportive_cycles = 0
                opposing_cycles = 0
            last_material_change_at = (
                occurred_at
                if action in material
                else (
                    None if previous is None else previous.last_material_change_at
                )
            )
            projections[instrument_identifier] = _PriorProjection(
                prior_decision_identifier=str(payload["identifier"]),
                prior_action=action,
                prior_target_weight=payload.get("recommended_position_weight"),
                decided_at=occurred_at,
                consecutive_supportive_cycles=supportive_cycles,
                consecutive_opposing_cycles=opposing_cycles,
                last_material_change_at=last_material_change_at,
            )
            del payload

    # PriorDecisionContext historically uses the latest pre-cutoff thesis state by asset,
    # independent of ownership episode. Retain one enum per current symbol, not thesis
    # payloads or event objects.
    thesis_states: dict[str, persistence.ThesisState] = {}
    thesis_type = persistence.CIOJournalEventType.THESIS_SNAPSHOT.value
    with self._connect() as connection:
        cursor = connection.execute(
            """
            SELECT occurred_at, payload_json
            FROM cio_journal_events
            WHERE event_type = ?
            ORDER BY sequence ASC
            """,
            (thesis_type,),
        )
        for row in cursor:
            occurred_at = _row_datetime(row["occurred_at"], field_name="occurred_at")
            if occurred_at >= decision_time:
                continue
            payload = _json_object(str(row["payload_json"]), field_name="payload_json")
            asset = str(payload.get("asset") or "")
            if asset in symbols:
                thesis_states[asset] = persistence.ThesisState(payload["state"])
            del payload

    results = []
    for candidate in candidates:
        instrument_identifier = str(candidate.instrument.instrument_id)
        projection = projections.get(instrument_identifier)
        if projection is None:
            continue
        symbol = str(candidate.instrument.symbol)
        results.append(
            persistence.PriorDecisionContext(
                candidate_identifier=candidate.identifier,
                prior_decision_identifier=projection.prior_decision_identifier,
                prior_action=projection.prior_action,
                prior_target_weight=projection.prior_target_weight,
                decided_at=projection.decided_at,
                thesis_state=thesis_states.get(symbol, persistence.ThesisState.CANDIDATE),
                consecutive_supportive_cycles=(
                    projection.consecutive_supportive_cycles
                ),
                consecutive_opposing_cycles=(
                    projection.consecutive_opposing_cycles
                ),
                last_material_change_at=projection.last_material_change_at,
                emergency_override=False,
            )
        )
    return tuple(results)


def _living_thesis(payload: Mapping[str, Any]) -> persistence.LivingThesis:
    return persistence.LivingThesis(
        identifier=payload["identifier"],
        decision_identifier=payload["decision_identifier"],
        candidate_identifier=payload["candidate_identifier"],
        asset=payload["asset"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        state=persistence.ThesisState(payload["state"]),
        original_rationale=payload["original_rationale"],
        assumptions=tuple(payload["assumptions"]),
        expected_return=payload["expected_return"],
        expected_downside=payload["expected_downside"],
        horizon_days=payload["horizon_days"],
        catalysts=tuple(payload["catalysts"]),
        invalidation_conditions=tuple(payload["invalidation_conditions"]),
        monitoring_indicators=tuple(payload["monitoring_indicators"]),
        initial_confidence=payload["initial_confidence"],
        current_confidence=payload["current_confidence"],
        evidence_identifiers=tuple(payload["evidence_identifiers"]),
        performance_since_approval=payload["performance_since_approval"],
        next_review_at=datetime.fromisoformat(payload["next_review_at"]),
        review_count=payload.get("review_count", 0),
        ownership_episode_identifier=(
            payload.get("ownership_episode_identifier") or payload["identifier"]
        ),
    )


def _bounded_active_theses(
    self: persistence.SQLiteCIOJournal,
    candidates,
    *,
    as_of: datetime,
):
    """Retain only latest active thesis objects for current symbols while streaming."""

    decision_time = persistence._aware(as_of, field_name="as_of")
    symbols = {str(item.instrument.symbol) for item in candidates}
    if not symbols:
        return ()
    active_states = {
        persistence.ThesisState.ACTIVE,
        persistence.ThesisState.STRENGTHENING,
        persistence.ThesisState.STABLE,
        persistence.ThesisState.WEAKENING,
        persistence.ThesisState.REDUCED,
    }
    latest_active: dict[str, persistence.LivingThesis] = {}
    thesis_type = persistence.CIOJournalEventType.THESIS_SNAPSHOT.value
    with self._connect() as connection:
        cursor = connection.execute(
            """
            SELECT occurred_at, payload_json
            FROM cio_journal_events
            WHERE event_type = ?
            ORDER BY sequence ASC
            """,
            (thesis_type,),
        )
        for row in cursor:
            occurred_at = _row_datetime(row["occurred_at"], field_name="occurred_at")
            if occurred_at >= decision_time:
                continue
            payload = _json_object(str(row["payload_json"]), field_name="payload_json")
            asset = str(payload.get("asset") or "")
            if asset not in symbols:
                del payload
                continue
            episode = str(
                payload.get("ownership_episode_identifier")
                or payload.get("identifier")
                or ""
            )
            state = persistence.ThesisState(payload["state"])
            if state in active_states:
                latest_active[episode] = _living_thesis(payload)
            else:
                latest_active.pop(episode, None)
            del payload
    return tuple(sorted(latest_active.values(), key=lambda item: item.asset))


def install_bounded_cio_journal_reads() -> None:
    """Install the bounded production read model idempotently on SQLiteCIOJournal."""

    journal = persistence.SQLiteCIOJournal
    current = (
        journal.verify_integrity,
        journal.prior_decision_contexts,
        journal.active_theses,
    )
    bounded = (
        _bounded_verify_integrity,
        _bounded_prior_decision_contexts,
        _bounded_active_theses,
    )
    if current == bounded:
        return
    originals = (
        _ORIGINAL_VERIFY_INTEGRITY,
        _ORIGINAL_PRIOR_DECISION_CONTEXTS,
        _ORIGINAL_ACTIVE_THESES,
    )
    if current != originals:
        raise RuntimeError("CIO journal read methods have unexpected implementations")
    journal.verify_integrity = _bounded_verify_integrity
    journal.prior_decision_contexts = _bounded_prior_decision_contexts
    journal.active_theses = _bounded_active_theses


__all__ = ["install_bounded_cio_journal_reads"]
