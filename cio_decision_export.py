"""Build a portable, credential-safe JSON bundle for one CIO decision lineage.

This module is presentation-only. It reads already-persisted records supplied by the
caller and cannot collect evidence, alter a decision, change construction, authorize
execution, or enable real money.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from providers.redundancy_audit import redundancy_audit_snapshot


_SCHEMA_VERSION = "cio-decision-export.v2"
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
_RELEASE_ENVIRONMENT_KEYS = (
    "RENDER_GIT_COMMIT",
    "GIT_COMMIT",
    "SOURCE_VERSION",
    "COMMIT_SHA",
    "GITHUB_SHA",
)
_NO_EXECUTABLE_ACTIONS = frozenset(
    {
        "hold",
        "watch",
        "insufficient_evidence",
        "no_superior_opportunity",
        "no_material_change",
    }
)


def _mapping(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _redact(value: object, *, key: str = "") -> object:
    normalized_key = key.strip().lower()
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
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


def _decision_identifier(
    record_name: str,
    record: Mapping[str, Any] | None,
) -> str:
    if not isinstance(record, Mapping):
        return ""
    if record_name == "cio_decision":
        return _field(record, "decision_identifier", "identifier")
    return _field(record, "decision_identifier")


def _cycle_identifier(record: Mapping[str, Any] | None) -> str:
    return _field(record, "cycle_identifier", "cycle_key")


def _construction_matches_cycle(
    construction: Mapping[str, Any],
    cycle_identifier: str,
) -> bool:
    if not cycle_identifier:
        return False
    direct = _cycle_identifier(construction)
    if direct:
        return direct == cycle_identifier
    journal = construction.get("journal")
    if isinstance(journal, Mapping):
        aggregate = _field(journal, "aggregate_identifier", "event_identifier")
        return bool(aggregate and cycle_identifier in aggregate)
    return False


def _record_reference(
    record_name: str,
    record: Mapping[str, Any] | None,
) -> dict[str, str]:
    if not isinstance(record, Mapping):
        return {}
    return {
        key: value
        for key, value in {
            "decision_identifier": _decision_identifier(record_name, record),
            "cycle_identifier": _cycle_identifier(record),
            "snapshot_identifier": _field(record, "snapshot_identifier"),
            "as_of": _field(record, "as_of", "decision_as_of"),
            "code_version": _field(record, "code_version"),
        }.items()
        if value
    }


def _iter_mappings(values: Iterable[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    if values is None:
        return ()
    return tuple(value for value in values if isinstance(value, Mapping))


def _first_matching(
    records: Iterable[Mapping[str, Any]],
    predicate,
) -> Mapping[str, Any] | None:
    return next((record for record in records if predicate(record)), None)


def select_cio_decision_records(
    *,
    daily_cio_briefing: Mapping[str, Any] | None,
    cio_decisions: Iterable[Mapping[str, Any]] | None = None,
    decision_evidence_snapshots: Iterable[Mapping[str, Any]] | None = None,
    portfolio_constructions: Iterable[Mapping[str, Any]] | None = None,
    decision_evaluations: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Mapping[str, Any] | None]:
    """Select records that belong to the briefing's exact decision lineage.

    Histories must be supplied newest-first. Missing matching records remain absent;
    the function never substitutes an unrelated latest record.
    """

    briefing = _mapping(daily_cio_briefing)
    target_decision = _decision_identifier("daily_cio_briefing", briefing)
    target_cycle = _cycle_identifier(briefing)

    decisions = _iter_mappings(cio_decisions)
    snapshots = _iter_mappings(decision_evidence_snapshots)
    constructions = _iter_mappings(portfolio_constructions)
    evaluations = _iter_mappings(decision_evaluations)

    decision = _first_matching(
        decisions,
        lambda record: bool(target_decision)
        and _decision_identifier("cio_decision", record) == target_decision,
    )
    snapshot = _first_matching(
        snapshots,
        lambda record: bool(target_decision)
        and _decision_identifier("decision_evidence_snapshot", record)
        == target_decision,
    )
    construction = _first_matching(
        constructions,
        lambda record: (
            bool(target_decision)
            and _decision_identifier("portfolio_construction", record)
            == target_decision
        )
        or _construction_matches_cycle(record, target_cycle),
    )
    evaluation = _first_matching(
        evaluations,
        lambda record: bool(target_decision)
        and _decision_identifier("decision_evaluation", record) == target_decision,
    )
    return {
        "cio_decision": decision,
        "daily_cio_briefing": briefing,
        "decision_evidence_snapshot": snapshot,
        "portfolio_construction": construction,
        "decision_evaluation": evaluation,
    }


def _release_identifier(explicit: str | None) -> tuple[str | None, str]:
    supplied = _first_text(explicit)
    if supplied:
        return supplied, "explicit"
    for key in _RELEASE_ENVIRONMENT_KEYS:
        value = _first_text(os.getenv(key))
        if value:
            return value, f"environment:{key}"
    return None, "unavailable"


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _evaluation_status(
    *,
    evaluation: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
    decision_as_of: str,
    generated_at: datetime,
) -> dict[str, Any]:
    if evaluation is not None:
        return {
            "status": _field(evaluation, "status") or "recorded",
            "recorded": True,
            "due_at": None,
        }
    horizon_text = _first_text(
        decision.get("decision_horizon_days") if isinstance(decision, Mapping) else None
    )
    try:
        horizon_days = int(horizon_text)
    except (TypeError, ValueError):
        horizon_days = 0
    decided_at = _parse_datetime(decision_as_of)
    if decided_at is None or horizon_days <= 0:
        return {
            "status": "pending_without_resolved_due_date",
            "recorded": False,
            "due_at": None,
        }
    due_at = decided_at + timedelta(days=horizon_days)
    return {
        "status": "pending_horizon" if generated_at < due_at else "overdue",
        "recorded": False,
        "due_at": due_at.isoformat(),
    }


def _decision_actions(decision: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(decision, Mapping):
        return {
            "selected_action": None,
            "effective_action": None,
            "deferred": False,
            "hysteresis_applied": False,
        }
    effective = _field(decision, "action") or None
    hysteresis = bool(decision.get("hysteresis_applied", False))
    deferred_action = _field(decision, "deferred_action")
    selected = deferred_action if hysteresis and deferred_action else effective
    return {
        "selected_action": selected,
        "effective_action": effective,
        "deferred": bool(selected and effective and selected != effective),
        "hysteresis_applied": hysteresis,
        "persistence_cycles": decision.get("persistence_cycles"),
        "rationale": decision.get("rationale"),
    }


def build_cio_decision_export(
    *,
    cio_decision: Mapping[str, Any] | None,
    daily_cio_briefing: Mapping[str, Any] | None,
    decision_evidence_snapshot: Mapping[str, Any] | None,
    portfolio_construction: Mapping[str, Any] | None,
    decision_evaluation: Mapping[str, Any] | None,
    generated_at: datetime | None = None,
    release_identifier: str | None = None,
) -> dict[str, Any]:
    """Return one immutable-style export bundle from one decision lineage."""

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)

    supplied = {
        "cio_decision": _mapping(cio_decision),
        "daily_cio_briefing": _mapping(daily_cio_briefing),
        "decision_evidence_snapshot": _mapping(decision_evidence_snapshot),
        "portfolio_construction": _mapping(portfolio_construction),
        "decision_evaluation": _mapping(decision_evaluation),
    }
    briefing = supplied["daily_cio_briefing"]
    decision = supplied["cio_decision"]
    target_decision = _first_text(
        _decision_identifier("daily_cio_briefing", briefing),
        _decision_identifier("cio_decision", decision),
    )
    target_cycle = _first_text(
        _cycle_identifier(briefing),
        _cycle_identifier(decision),
        _cycle_identifier(supplied["decision_evidence_snapshot"]),
    )

    lineage_issues: list[str] = []
    records: dict[str, dict[str, Any] | None] = {}
    for name, record in supplied.items():
        if record is None:
            records[name] = None
            continue
        record_decision = _decision_identifier(name, record)
        if name == "portfolio_construction":
            aligned = bool(
                (record_decision and record_decision == target_decision)
                or _construction_matches_cycle(record, target_cycle)
            )
            if not aligned:
                lineage_issues.append("portfolio_construction:lineage_unproven")
                records[name] = None
                continue
        elif name != "daily_cio_briefing" and target_decision:
            if not record_decision or record_decision != target_decision:
                lineage_issues.append(f"{name}:decision_identifier_mismatch")
                records[name] = None
                continue
        records[name] = record

    briefing = records["daily_cio_briefing"]
    decision = records["cio_decision"]
    evidence = records["decision_evidence_snapshot"]
    construction = records["portfolio_construction"]
    evaluation = records["decision_evaluation"]

    if not target_decision:
        lineage_issues.append("decision_identifier:missing")
    if briefing is None:
        lineage_issues.append("daily_cio_briefing:missing")
    if decision is None:
        lineage_issues.append("cio_decision:missing_for_decision")
    if evidence is None:
        lineage_issues.append("decision_evidence_snapshot:missing_for_decision")

    actions = _decision_actions(decision)
    selected_action = str(actions.get("selected_action") or "")
    effective_action = str(actions.get("effective_action") or "")
    executable_now = effective_action not in _NO_EXECUTABLE_ACTIONS and bool(effective_action)
    if executable_now and construction is None:
        lineage_issues.append("portfolio_construction:missing_for_executable_action")

    references = {
        name: _record_reference(name, record)
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

    release, release_source = _release_identifier(release_identifier)
    decision_code_version = _field(decision, "code_version")
    decision_release_recorded = bool(
        decision_code_version and decision_code_version.lower() != "unknown"
    )
    if not decision_release_recorded:
        lineage_issues.append("cio_decision:code_version_not_recorded")

    decision_as_of = _first_text(
        _field(briefing, "as_of", "decision_as_of"),
        _field(decision, "as_of", "decision_as_of"),
        _field(evidence, "as_of", "decision_as_of"),
    )
    evaluation_state = _evaluation_status(
        evaluation=evaluation,
        decision=decision,
        decision_as_of=decision_as_of,
        generated_at=timestamp,
    )
    construction_state = (
        "aligned"
        if construction is not None
        else (
            "not_applicable_no_executable_action"
            if not executable_now
            else "missing_for_executable_action"
        )
    )

    unique_issues = tuple(dict.fromkeys(lineage_issues))
    auditable = not unique_issues
    consistency_state = "aligned" if auditable else "non_auditable"

    bundle: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": timestamp.isoformat(),
        "portfolio_code": "COMPOUNDING",
        "decision_identifier": target_decision,
        "cycle_identifier": target_cycle,
        "snapshot_identifier": _first_text(
            _field(briefing, "snapshot_identifier"),
            _field(decision, "snapshot_identifier"),
            _field(evidence, "snapshot_identifier", "identifier"),
        ),
        "decision_as_of": decision_as_of,
        "decision_actions": actions,
        "release_identity": {
            "export_runtime_release": release,
            "export_runtime_release_source": release_source,
            "decision_code_version": decision_code_version or None,
            "decision_release_recorded": decision_release_recorded,
        },
        "component_status": {
            "portfolio_construction": construction_state,
            "decision_evaluation": evaluation_state,
        },
        "auditability": {
            "status": "auditable" if auditable else "non_auditable",
            "issues": list(unique_issues),
            "mixed_records_included": False,
            "target_decision_identifier": target_decision or None,
            "target_cycle_identifier": target_cycle or None,
        },
        "record_presence": {name: records[name] is not None for name in _RECORD_NAMES},
        "record_consistency": {
            "state": consistency_state,
            "known_as_of_values": known_as_of_values,
            "known_cycle_identifiers": known_cycle_values,
            "references": references,
        },
        "records": records,
        "provider_redundancy_audit": redundancy_audit_snapshot(),
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
        digest = hashlib.sha256(
            cio_decision_export_json(bundle).encode("utf-8")
        ).hexdigest()[:12]
        identifier = f"unidentified-{digest}"
    safe_identifier = _SAFE_IDENTIFIER.sub("-", identifier).strip("-._")[:96]
    if not safe_identifier:
        safe_identifier = "decision"
    return f"cio-decision-{safe_identifier}.json"


__all__ = [
    "build_cio_decision_export",
    "cio_decision_export_filename",
    "cio_decision_export_json",
    "select_cio_decision_records",
]
