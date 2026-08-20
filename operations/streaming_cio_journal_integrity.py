"""Bound CIO journal payload validation without materializing nested JSON objects.

The append-only journal hash chain remains authoritative and complete.  This module only
changes how each stored ``payload_json`` value is syntactically validated during integrity
scans: the raw SQLite string is walked in place instead of being expanded by ``json.loads``.
Peak validation memory is therefore independent of a single event's nested payload size.

No journal row is skipped.  Sequence, previous-hash, content-hash, event identity, schema,
and top-level JSON-object requirements remain fail-closed.  Investment logic, evidence,
CIO authority, construction, paper execution, and real-money denial are unchanged.
"""
from __future__ import annotations

from datetime import datetime

import cio.persistence as persistence
import operations.bounded_cio_journal as bounded


_ORIGINAL_BOUNDED_VERIFY_INTEGRITY = bounded._bounded_verify_integrity


class _JSONSyntaxError(ValueError):
    pass


class _JSONTextValidator:
    """Validate JSON directly against one existing string with O(nesting-depth) memory."""

    __slots__ = ("text", "position", "length")

    def __init__(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("payload_json must be a JSON string")
        self.text = text
        self.position = 0
        self.length = len(text)

    def _error(self, message: str) -> _JSONSyntaxError:
        return _JSONSyntaxError(
            f"payload_json must be valid JSON: {message} at character {self.position}"
        )

    def _skip_space(self) -> None:
        text = self.text
        position = self.position
        length = self.length
        while position < length and text[position] in " \t\r\n":
            position += 1
        self.position = position

    def _peek(self) -> str | None:
        self._skip_space()
        if self.position >= self.length:
            return None
        return self.text[self.position]

    def _expect(self, token: str) -> None:
        self._skip_space()
        if self.position >= self.length or self.text[self.position] != token:
            raise self._error(f"expected {token!r}")
        self.position += 1

    def _string(self) -> None:
        self._skip_space()
        if self.position >= self.length or self.text[self.position] != '"':
            raise self._error("expected string")
        self.position += 1
        text = self.text
        length = self.length
        while self.position < length:
            character = text[self.position]
            self.position += 1
            if character == '"':
                return
            if ord(character) < 0x20:
                raise self._error("unescaped control character in string")
            if character != "\\":
                continue
            if self.position >= length:
                raise self._error("unterminated escape sequence")
            escaped = text[self.position]
            self.position += 1
            if escaped in '"\\/bfnrt':
                continue
            if escaped != "u":
                raise self._error("invalid string escape")
            if self.position + 4 > length:
                raise self._error("truncated unicode escape")
            for index in range(self.position, self.position + 4):
                if text[index] not in "0123456789abcdefABCDEF":
                    raise self._error("invalid unicode escape")
            self.position += 4
        raise self._error("unterminated string")

    def _literal(self, literal: str) -> None:
        self._skip_space()
        end = self.position + len(literal)
        if end > self.length or self.text[self.position:end] != literal:
            raise self._error(f"expected {literal!r}")
        self.position = end

    def _number(self) -> None:
        self._skip_space()
        text = self.text
        length = self.length
        position = self.position
        if position < length and text[position] == "-":
            position += 1
        if position >= length:
            raise self._error("incomplete number")
        if text[position] == "0":
            position += 1
            if position < length and text[position].isdigit():
                raise self._error("leading zero in number")
        elif text[position] in "123456789":
            position += 1
            while position < length and text[position].isdigit():
                position += 1
        else:
            raise self._error("invalid number")
        if position < length and text[position] == ".":
            position += 1
            fraction_start = position
            while position < length and text[position].isdigit():
                position += 1
            if position == fraction_start:
                raise self._error("fraction requires digits")
        if position < length and text[position] in "eE":
            position += 1
            if position < length and text[position] in "+-":
                position += 1
            exponent_start = position
            while position < length and text[position].isdigit():
                position += 1
            if position == exponent_start:
                raise self._error("exponent requires digits")
        self.position = position

    def _value(self) -> None:
        token = self._peek()
        if token is None:
            raise self._error("expected value")
        if token == '"':
            self._string()
            return
        if token == "{":
            self._object()
            return
        if token == "[":
            self._array()
            return
        if token == "t":
            self._literal("true")
            return
        if token == "f":
            self._literal("false")
            return
        if token == "n":
            self._literal("null")
            return
        if token == "-" or token.isdigit():
            self._number()
            return
        raise self._error("unexpected value token")

    def _object(self) -> None:
        self._expect("{")
        if self._peek() == "}":
            self._expect("}")
            return
        while True:
            self._string()
            self._expect(":")
            self._value()
            delimiter = self._peek()
            if delimiter == ",":
                self._expect(",")
                continue
            if delimiter == "}":
                self._expect("}")
                return
            raise self._error("expected ',' or '}' in object")

    def _array(self) -> None:
        self._expect("[")
        if self._peek() == "]":
            self._expect("]")
            return
        while True:
            self._value()
            delimiter = self._peek()
            if delimiter == ",":
                self._expect(",")
                continue
            if delimiter == "]":
                self._expect("]")
                return
            raise self._error("expected ',' or ']' in array")

    def validate_object_document(self) -> None:
        self._skip_space()
        if self._peek() != "{":
            raise self._error("top-level value must be an object")
        self._object()
        self._skip_space()
        if self.position != self.length:
            raise self._error("trailing data after object")


def validate_json_object_text(payload_json: str) -> None:
    """Validate one canonical payload without allocating its nested object graph."""

    try:
        _JSONTextValidator(payload_json).validate_object_document()
    except RecursionError as error:
        raise _JSONSyntaxError("payload_json nesting exceeds the validation limit") from error


def _streaming_verify_integrity(self: persistence.SQLiteCIOJournal) -> bool:
    """Verify the complete append-only chain with bounded payload-validation memory."""

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
            occurred_at = bounded._row_datetime(
                row["occurred_at"], field_name="occurred_at"
            )
            recorded_at = bounded._row_datetime(
                row["recorded_at"], field_name="recorded_at"
            )
            schema_version = persistence._required_text(
                str(row["schema_version"]), field_name="schema_version"
            )
            payload_json = row["payload_json"]
            if not isinstance(payload_json, str):
                raise persistence.CIOJournalIntegrityError(
                    "CIO journal payload_json is not text"
                )
            try:
                validate_json_object_text(payload_json)
            except (TypeError, ValueError) as error:
                raise persistence.CIOJournalIntegrityError(
                    "CIO journal payload_json is not a valid JSON object"
                ) from error
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


def install_streaming_cio_journal_integrity() -> None:
    """Install the bounded verifier before the normal bounded-journal installer runs."""

    current_projection = bounded._bounded_verify_integrity
    journal = persistence.SQLiteCIOJournal
    current_journal = journal.verify_integrity

    if current_projection is _streaming_verify_integrity:
        if current_journal is _ORIGINAL_BOUNDED_VERIFY_INTEGRITY:
            journal.verify_integrity = _streaming_verify_integrity
        return
    if current_projection is not _ORIGINAL_BOUNDED_VERIFY_INTEGRITY:
        raise RuntimeError("bounded CIO journal verifier has an unexpected implementation")

    bounded._bounded_verify_integrity = _streaming_verify_integrity
    if current_journal is _ORIGINAL_BOUNDED_VERIFY_INTEGRITY:
        journal.verify_integrity = _streaming_verify_integrity


__all__ = [
    "install_streaming_cio_journal_integrity",
    "validate_json_object_text",
]
