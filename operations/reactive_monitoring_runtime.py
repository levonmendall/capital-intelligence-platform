"""Consume the active-investor reactive monitoring plan without granting authority.

The active-investor cycle already publishes a point-in-time ReactiveMonitoringPlan to
its append-only hash chain.  This module is the governed read/evaluation boundary for
that plan.  A match may request a canonical CIO reassessment; it can never create a
candidate, change a target, authorize execution, alter policy, or authorize real money.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from portfolio.active_investor import SQLiteActiveInvestorStore


_DISALLOWED_QUALITY = frozenset({"disputed", "unverified", "missing", "fixture", "stale"})
_GENERIC_WORDS = frozenset(
    {
        "change",
        "changes",
        "material",
        "market",
        "portfolio",
        "position",
        "review",
        "score",
        "signal",
        "value",
    }
)
_KIND_CHANNELS: Mapping[str, frozenset[str]] = {
    "flow_reversal": frozenset({"positioning", "liquidity", "supply", "demand", "volatility"}),
    "expectations_gap": frozenset({"earnings", "growth", "inflation", "sentiment", "policy"}),
    "regime_transition": frozenset({"growth", "inflation", "policy", "liquidity", "credit", "currency", "volatility"}),
    "rates_credit": frozenset({"discount_rate", "credit", "policy", "liquidity"}),
    "volatility_breadth": frozenset({"volatility", "positioning", "liquidity"}),
    "earnings_guidance": frozenset({"earnings", "sentiment"}),
    "thesis_invalidation": frozenset({"earnings", "credit", "regulation", "operational", "counterparty", "geopolitical"}),
    "replacement_opportunity": frozenset({"earnings", "growth", "sentiment", "positioning"}),
    "risk_budget": frozenset({"volatility", "credit", "liquidity", "currency"}),
    "catalyst": frozenset({"earnings", "regulation", "policy", "operational", "geopolitical", "sentiment"}),
}


@dataclass(frozen=True, slots=True)
class ReactiveMonitoringMatch:
    """One qualified evidence/dependency match with reassessment-only semantics."""

    record_identifier: str
    dependency_identifier: str
    kind: str
    topic: str
    priority: float
    incremental_reassessment: bool
    full_cycle_required: bool
    reassessment_authority: bool = False
    paper_only: bool = True
    real_money_authorized: bool = False

    def reason(self) -> str:
        mode = "full-cycle" if self.full_cycle_required else "incremental"
        return (
            f"reactive monitoring dependency {self.dependency_identifier} "
            f"({self.kind}, {mode}) matched qualified evidence: {self.topic}"
        )


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    for field_name in ("available_at", "published_at", "event_at"):
        value = _parse_time(record.get(field_name))
        if value is not None:
            return value
    return None


def _number(record: Mapping[str, Any], field_name: str, default: float = 0.0) -> float:
    value = record.get(field_name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _quality_state(record: Mapping[str, Any]) -> str:
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        return ""
    return str(provenance.get("quality_state", "")).strip().lower()


def _record_identifier(record: Mapping[str, Any]) -> str:
    value = str(record.get("identifier", "")).strip()
    if value:
        return value
    material = json.dumps(dict(record), sort_keys=True, separators=(",", ":"), default=str)
    return "public-record:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _record_text(record: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in ("topic", "title", "summary", "description", "text"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    for key in ("tags", "entities", "symbols", "impact_channels"):
        value = record.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values.extend(str(item) for item in value if str(item).strip())
    return " ".join(values).lower()


def _tokens(values: Iterable[object]) -> frozenset[str]:
    result: set[str] = set()
    for value in values:
        normalized = str(value).replace("_", " ").replace("-", " ").lower()
        for token in re.findall(r"[a-z0-9.]+", normalized):
            if len(token) >= 4 and token not in _GENERIC_WORDS:
                result.add(token)
    return frozenset(result)


def _qualified(record: Mapping[str, Any], *, as_of: datetime) -> bool:
    available = _record_time(record)
    if available is None or available > as_of.astimezone(timezone.utc):
        return False
    if _quality_state(record) in _DISALLOWED_QUALITY:
        return False
    reliability = _number(record, "reliability")
    relevance = _number(record, "relevance")
    materiality = _number(record, "materiality")
    strength = reliability * relevance * materiality
    return strength >= 0.18 or (materiality >= 0.75 and reliability >= 0.60)


def _validate_plan(plan: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    if plan.get("reassessment_authority") is not False:
        raise ValueError("reactive monitoring plan must explicitly deny reassessment authority")
    dependencies = plan.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("reactive monitoring plan dependencies are unavailable")
    result: list[Mapping[str, Any]] = []
    for item in dependencies:
        if not isinstance(item, Mapping):
            raise ValueError("reactive monitoring dependency is invalid")
        if item.get("reassessment_authority") is not False:
            raise ValueError("reactive monitoring dependency must explicitly deny reassessment authority")
        identifier = str(item.get("identifier", "")).strip()
        kind = str(item.get("kind", "")).strip()
        if not identifier or kind not in _KIND_CHANNELS:
            raise ValueError("reactive monitoring dependency identity/kind is invalid")
        result.append(item)
    return tuple(result)


def load_latest_reactive_monitoring_plan(database_path: str | Path) -> Mapping[str, Any] | None:
    """Return the latest hash-chain-verified monitoring plan, if one exists."""

    path = Path(database_path).expanduser()
    if not path.is_file():
        return None
    store = SQLiteActiveInvestorStore(path)
    store.verify_integrity()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT payload_json
            FROM active_investor_events
            WHERE event_type = 'reactive_monitoring'
            ORDER BY sequence DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError as error:
        raise ValueError("reactive monitoring plan payload is invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("reactive monitoring plan payload is invalid")
    _validate_plan(payload)
    return payload


def match_reactive_dependencies(
    *,
    plan: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    as_of: datetime,
    acknowledged_record_identifiers: Iterable[str] = (),
) -> tuple[ReactiveMonitoringMatch, ...]:
    """Match qualified point-in-time evidence to declared monitoring dependencies.

    This function produces reassessment requests only.  It deliberately has no
    mutation or execution path.
    """

    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    dependencies = _validate_plan(plan)
    acknowledged = {str(item) for item in acknowledged_record_identifiers if str(item).strip()}
    matches: list[ReactiveMonitoringMatch] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not _qualified(record, as_of=as_of):
            continue
        record_identifier = _record_identifier(record)
        if record_identifier in acknowledged:
            continue
        channels = {
            str(item).strip().lower()
            for item in (record.get("impact_channels") or ())
            if str(item).strip()
        }
        text = _record_text(record)
        topic = " ".join(str(record.get("topic", "qualified public evidence")).split())[:240]
        record_tokens = _tokens((text,))
        for dependency in dependencies:
            kind = str(dependency["kind"])
            declared_tokens = _tokens(
                (
                    *(dependency.get("evidence_inputs") or ()),
                    *(dependency.get("affected_candidates") or ()),
                    *(dependency.get("affected_sleeves") or ()),
                )
            )
            explicit_match = bool(record_tokens.intersection(declared_tokens))
            channel_match = bool(channels.intersection(_KIND_CHANNELS[kind]))
            if not explicit_match and not channel_match:
                continue
            dependency_identifier = str(dependency["identifier"])
            key = (record_identifier, dependency_identifier)
            if key in seen:
                continue
            seen.add(key)
            priority = dependency.get("priority", 0.0)
            if isinstance(priority, bool) or not isinstance(priority, (int, float)):
                priority = 0.0
            matches.append(
                ReactiveMonitoringMatch(
                    record_identifier=record_identifier,
                    dependency_identifier=dependency_identifier,
                    kind=kind,
                    topic=topic,
                    priority=max(0.0, min(1.0, float(priority))),
                    incremental_reassessment=dependency.get("incremental_reassessment") is True,
                    full_cycle_required=dependency.get("full_cycle_required") is True,
                )
            )
    return tuple(
        sorted(
            matches,
            key=lambda item: (-item.priority, item.record_identifier, item.dependency_identifier),
        )
    )


__all__ = [
    "ReactiveMonitoringMatch",
    "load_latest_reactive_monitoring_plan",
    "match_reactive_dependencies",
]
