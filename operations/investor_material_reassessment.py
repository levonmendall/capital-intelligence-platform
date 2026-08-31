"""Investor-grade material reassessment on top of the live market scanner.

The existing scanner remains authoritative for price and market-hours handling. This
extension adds content-aware public-evidence materiality so credit, rates, inflation,
currency, volatility, positioning, earnings, policy, geopolitical, operational, and
counterparty changes can request a canonical CIO reassessment before or without a
large price move.

Deduplication is opportunity-specific. A recently reviewed market event cannot delay a
different qualified public-evidence opportunity.

The scanner requests review only. It has no candidate, CIO-action, sizing,
construction, execution, policy-change, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from operations.cio_material_reassessment import (
    MaterialCIOReassessmentEngine as _PriceMaterialCIOReassessmentEngine,
    ReassessmentResult,
    aware_utc,
    load_json,
    parse_datetime,
    save_json,
)


_MATERIAL_CHANNELS = frozenset(
    {
        "growth",
        "inflation",
        "policy",
        "liquidity",
        "discount_rate",
        "earnings",
        "credit",
        "supply",
        "demand",
        "commodity",
        "currency",
        "volatility",
        "regulation",
        "geopolitical",
        "operational",
        "cyber",
        "climate_weather",
        "positioning",
        "sentiment",
        "counterparty",
    }
)
_DISALLOWED_QUALITY = frozenset(
    {"disputed", "unverified", "missing", "fixture", "stale"}
)
_ACKNOWLEDGED_LIMIT = 4000


def _read_records(path: Path) -> tuple[Mapping[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    values = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(values, list):
        return ()
    return tuple(item for item in values if isinstance(item, Mapping))


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    for field_name in ("available_at", "published_at", "event_at"):
        value = parse_datetime(record.get(field_name))
        if value is not None:
            return value
    return None


def _record_identifier(record: Mapping[str, Any]) -> str:
    value = str(record.get("identifier", "")).strip()
    if value:
        return value
    material = json.dumps(
        dict(record),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "public-record:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _quality_state(record: Mapping[str, Any]) -> str:
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        return ""
    return str(provenance.get("quality_state", "")).strip().lower()


def _number(record: Mapping[str, Any], field_name: str, default: float) -> float:
    value = record.get(field_name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _material_record(
    record: Mapping[str, Any],
    *,
    as_of: datetime,
) -> tuple[str, tuple[str, ...], str, float] | None:
    available_at = _record_time(record)
    if available_at is None or available_at > as_of:
        return None
    quality = _quality_state(record)
    if quality in _DISALLOWED_QUALITY:
        return None
    channels = tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in (record.get("impact_channels") or ())
            if str(item).strip().lower() in _MATERIAL_CHANNELS
        )
    )
    if not channels:
        return None
    reliability = _number(record, "reliability", 0.0)
    relevance = _number(record, "relevance", 0.0)
    materiality = _number(record, "materiality", 0.0)
    strength = reliability * relevance * materiality
    independently_material = materiality >= 0.75 and reliability >= 0.60
    if strength < 0.18 and not independently_material:
        return None
    topic = " ".join(str(record.get("topic", "material public evidence")).split())
    return (
        _record_identifier(record),
        channels,
        topic[:240],
        round(strength, 8),
    )


class InvestorMaterialCIOReassessmentEngine(
    _PriceMaterialCIOReassessmentEngine
):
    """Request canonical reassessment for price or content-level material changes."""

    def _public_material_changes(
        self,
        *,
        now: datetime,
        public_collection: object | None,
        state: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        records_path = getattr(public_collection, "records_path", None)
        if records_path is None and isinstance(public_collection, Mapping):
            records_path = public_collection.get("records_path")
        if records_path is None:
            return (), ()
        acknowledged = {
            str(item)
            for item in (
                state.get("acknowledged_public_record_identifiers", ()) or ()
            )
            if str(item).strip()
        }
        observations = []
        for record in _read_records(Path(records_path)):
            material = _material_record(record, as_of=now)
            if material is None or material[0] in acknowledged:
                continue
            observations.append(material)
        if not observations:
            return (), ()
        observations.sort(key=lambda item: (-item[3], item[0]))
        identifiers = tuple(item[0] for item in observations)
        reasons = tuple(
            dict.fromkeys(
                "new material public evidence affects "
                + ", ".join(item[1])
                + f": {item[2]}"
                for item in observations[:12]
            )
        )
        return identifiers, reasons

    def scan_if_due(
        self,
        *,
        now: datetime,
        public_collection: object | None = None,
    ) -> ReassessmentResult:
        timestamp = aware_utc(now, "now")
        base = super().scan_if_due(
            now=timestamp,
            public_collection=public_collection,
        )
        if base.state in {"not_due", "scheduled_guard", "failed"}:
            return base

        state = load_json(self.state_path)
        identifiers, public_reasons = self._public_material_changes(
            now=timestamp,
            public_collection=public_collection,
            state=state,
        )
        if not public_reasons:
            return base

        combined_reasons = tuple(dict.fromkeys((*base.reasons, *public_reasons)))
        state["pending_public_record_identifiers"] = list(
            dict.fromkeys(
                (
                    *tuple(
                        str(item)
                        for item in (
                            state.get("pending_public_record_identifiers", ()) or ()
                        )
                    ),
                    *identifiers,
                )
            )
        )[-_ACKNOWLEDGED_LIMIT:]
        opportunity_keys = tuple(f"public-record:{item}" for item in identifiers)

        if base.triggered and base.trigger_key is not None:
            self._attach_opportunities_to_trigger(
                state,
                trigger_key=base.trigger_key,
                opportunity_keys=opportunity_keys,
                timestamp=timestamp,
            )
            state["last_trigger_public_record_identifiers"] = list(identifiers)
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="triggered",
                evaluated_at=timestamp,
                triggered=True,
                trigger_key=base.trigger_key,
                reasons=combined_reasons,
                symbol_count=base.symbol_count,
                detail=(
                    "Material market movement and distinct content-level public "
                    "evidence request a full canonical CIO reassessment."
                ),
            )

        trigger_key, claimed = self._claim_distinct_opportunities(
            state,
            opportunity_keys=opportunity_keys,
            timestamp=timestamp,
            prefix="material-evidence",
        )
        if trigger_key is None:
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="deduplicated",
                evaluated_at=timestamp,
                reasons=combined_reasons,
                symbol_count=base.symbol_count,
                detail=(
                    "The same material public-evidence records already requested a "
                    "CIO reassessment; unrelated records remain independently eligible."
                ),
            )

        state["last_trigger_public_record_identifiers"] = [
            item
            for item in identifiers
            if f"public-record:{item}" in set(claimed)
        ]
        save_json(self.state_path, state)
        return ReassessmentResult(
            state="triggered",
            evaluated_at=timestamp,
            triggered=True,
            trigger_key=trigger_key,
            reasons=combined_reasons,
            symbol_count=base.symbol_count,
            detail=(
                "Distinct material growth, inflation, policy, liquidity, rates, "
                "earnings, credit, currency, volatility, positioning, or "
                "thesis-relevant public evidence requests an immediate canonical "
                "CIO reassessment."
            ),
        )

    def acknowledge_assessment(self, *, now: datetime) -> None:
        super().acknowledge_assessment(now=now)
        state = load_json(self.state_path)
        acknowledged = tuple(
            dict.fromkeys(
                (
                    *tuple(
                        str(item)
                        for item in (
                            state.get(
                                "acknowledged_public_record_identifiers",
                                (),
                            )
                            or ()
                        )
                    ),
                    *tuple(
                        str(item)
                        for item in (
                            state.get("pending_public_record_identifiers", ()) or ()
                        )
                    ),
                )
            )
        )[-_ACKNOWLEDGED_LIMIT:]
        state["acknowledged_public_record_identifiers"] = list(acknowledged)
        state.pop("pending_public_record_identifiers", None)
        state.pop("last_trigger_public_record_identifiers", None)
        save_json(self.state_path, state)


__all__ = ["InvestorMaterialCIOReassessmentEngine"]
