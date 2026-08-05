"""Build a portable, credential-safe JSON bundle for the latest CIO decision.

This module is presentation-only. It reads already-persisted records supplied by the
caller and cannot collect evidence, alter a decision, change construction, authorize
execution, or enable real money.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping


_SCHEMA_VERSION = "cio-decision-export.v1"
_RECORD_NAMES = (
    "cio_decision",
    "daily_cio_briefing",
    "decision_evidence_snapshot",
    "portfolio_construction",
    "decision_evaluation",
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "authorization",
        "credential",
        "password",
        "refresh_token",
        "secret_key",
    }
)
_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9._-]+")


def _mapping(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _redact(value: object, *, key: str = "") -> object:
    normalized_key = key.strip().lower()
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _field(record: Mapping[str, Any] | None, *names: str) -> str:
    if not isinstance(record, Mapping):
        return ""
    return _first_text(*(record.get(name) for name in names))


def _record_reference(record: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(record, Mapping):
        return {}
    return {
        key: value
        for key, value in {
            "decision_identifier": _field(record, "decision_identifier"),
            "cycle_identifier": _field(record, "cycle_identifier", "cycle_key"),
            "snapshot_identifier": _field(record, "snapshot_identifier"),
            "as_of": _field(record, "as_of", "decision_as_of"),
        }.items()
        if value
    }


def build_cio_decision_export(
    *,
    cio_decision: Mapping[str, Any] | None,
    daily_cio_briefing: Mapping[str, Any] | None,
    decision_evidence_snapshot: Mapping[str, Any] | None,
    portfolio_construction: Mapping[str, Any] | None,
    decision_evaluation: Mapping[str, Any] | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return one immutable-style export bundle from persisted CIO records."""

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)

    records = {
        "cio_decision": _mapping(cio_decision),
        "daily_cio_briefing": _mapping(daily_cio_briefing),
        "decision_evidence_snapshot": _mapping(decision_evidence_snapshot),
        "portfolio_construction": _mapping(portfolio_construction),
        "decision_evaluation": _mapping(decision_evaluation),
    }
    briefing = records["daily_cio_briefing"]
    decision = records["cio_decision"]
    construction = records["portfolio_construction"]
    evidence = records["decision_evidence_snapshot"]

    references = {
        name: _record_reference(record)
        for name, record in records.items()
        if record is not None
    }
    known_as_of_values = sorted(
        {
            reference["as_of"]
            for reference in references.values()
            if reference.get("as_of")
        }
    )
    known_cycle_values = sorted(
        {
            reference["cycle_identifier"]
            for reference in references.values()
            if reference.get("cycle_identifier")
        }
    )
    consistency_state = (
        "aligned"
        if len(known_as_of_values) <= 1 and len(known_cycle_values) <= 1
        else "mixed_latest_records"
    )

    bundle: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": timestamp.isoformat(),
        "portfolio_code": "COMPOUNDING",
        "decision_identifier": _first_text(
            _field(briefing, "decision_identifier", "identifier"),
            _field(decision, "decision_identifier", "identifier"),
            _field(construction, "decision_identifier"),
        ),
        "cycle_identifier": _first_text(
            _field(briefing, "cycle_identifier", "cycle_key"),
            _field(decision, "cycle_identifier", "cycle_key"),
            _field(evidence, "cycle_identifier", "cycle_key"),
        ),
        "snapshot_identifier": _first_text(
            _field(briefing, "snapshot_identifier"),
            _field(decision, "snapshot_identifier"),
            _field(evidence, "snapshot_identifier", "identifier"),
        ),
        "decision_as_of": _first_text(
            _field(briefing, "as_of", "decision_as_of"),
            _field(decision, "as_of", "decision_as_of"),
            _field(evidence, "as_of", "decision_as_of"),
        ),
        "record_presence": {name: records[name] is not None for name in _RECORD_NAMES},
        "record_consistency": {
            "state": consistency_state,
            "known_as_of_values": known_as_of_values,
            "known_cycle_identifiers": known_cycle_values,
            "references": references,
        },
        "records": records,
        "authority": {
            "read_only_export": True,
            "candidate_authority": False,
            "ranking_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
    }
    return _redact(bundle)  # type: ignore[return-value]


def cio_decision_export_json(bundle: Mapping[str, Any]) -> str:
    """Serialize a decision bundle as stable human-readable JSON."""

    return json.dumps(
        dict(bundle),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def cio_decision_export_filename(bundle: Mapping[str, Any]) -> str:
    """Return a short mobile-friendly filename with a deterministic fallback."""

    identifier = _first_text(
        bundle.get("decision_identifier"),
        bundle.get("snapshot_identifier"),
        bundle.get("cycle_identifier"),
    )
    if not identifier:
        digest = hashlib.sha256(cio_decision_export_json(bundle).encode("utf-8")).hexdigest()[:12]
        identifier = f"unidentified-{digest}"
    safe_identifier = _SAFE_IDENTIFIER.sub("-", identifier).strip("-._")[:96]
    if not safe_identifier:
        safe_identifier = "decision"
    return f"cio-decision-{safe_identifier}.json"


__all__ = [
    "build_cio_decision_export",
    "cio_decision_export_filename",
    "cio_decision_export_json",
]
