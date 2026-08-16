"""Reactive-plan-aware CIO reassessment with reassessment-only authority.

This layer composes the existing price/content materiality scanner with the latest
hash-chain-verified active-investor ReactiveMonitoringPlan.  A dependency match may
request a canonical CIO reassessment.  It cannot change a CIO action, construction,
portfolio state, execution instruction, policy, or real-money authorization.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from operations.cio_material_reassessment import (
    ReassessmentResult,
    aware_utc,
    load_json,
    parse_datetime,
    save_json,
)
from operations.investor_material_reassessment import (
    InvestorMaterialCIOReassessmentEngine,
    _read_records,
)
from operations.reactive_monitoring_runtime import (
    load_latest_reactive_monitoring_plan,
    match_reactive_dependencies,
)


_ACKNOWLEDGED_LIMIT = 4000


class ReactiveInvestorMaterialCIOReassessmentEngine(
    InvestorMaterialCIOReassessmentEngine
):
    """Request CIO reassessment when a declared reactive dependency is observed."""

    def __init__(
        self,
        *,
        active_investor_database: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.active_investor_database = (
            None
            if active_investor_database is None
            else Path(active_investor_database).expanduser()
        )

    @staticmethod
    def _records_path(public_collection: object | None) -> Path | None:
        value = getattr(public_collection, "records_path", None)
        if value is None and isinstance(public_collection, Mapping):
            value = public_collection.get("records_path")
        return None if value is None else Path(value)

    def _reactive_changes(
        self,
        *,
        now: datetime,
        public_collection: object | None,
        state: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        if self.active_investor_database is None:
            return (), (), ()
        records_path = self._records_path(public_collection)
        if records_path is None:
            return (), (), ()
        try:
            plan = load_latest_reactive_monitoring_plan(
                self.active_investor_database
            )
        except (OSError, ValueError):
            # A corrupt/unauthorized monitoring plan is fail-closed: it is ignored
            # and cannot create a reassessment request. The existing independent
            # price/content materiality scanner remains active.
            return (), (), ()
        if plan is None:
            return (), (), ()
        acknowledged = tuple(
            str(item)
            for item in (
                state.get("acknowledged_public_record_identifiers", ()) or ()
            )
            if str(item).strip()
        )
        matches = match_reactive_dependencies(
            plan=plan,
            records=_read_records(records_path),
            as_of=now,
            acknowledged_record_identifiers=acknowledged,
        )
        if not matches:
            return (), (), ()
        record_identifiers = tuple(
            dict.fromkeys(item.record_identifier for item in matches)
        )
        dependency_identifiers = tuple(
            dict.fromkeys(item.dependency_identifier for item in matches)
        )
        reasons = tuple(dict.fromkeys(item.reason() for item in matches[:12]))
        return record_identifiers, dependency_identifiers, reasons

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
        record_ids, dependency_ids, reactive_reasons = self._reactive_changes(
            now=timestamp,
            public_collection=public_collection,
            state=state,
        )
        if not reactive_reasons:
            return base

        combined_reasons = tuple(dict.fromkeys((*base.reasons, *reactive_reasons)))
        pending_records = tuple(
            dict.fromkeys(
                (
                    *tuple(
                        str(item)
                        for item in (
                            state.get("pending_public_record_identifiers", ()) or ()
                        )
                    ),
                    *record_ids,
                )
            )
        )[-_ACKNOWLEDGED_LIMIT:]
        state["pending_public_record_identifiers"] = list(pending_records)
        state["pending_reactive_dependency_identifiers"] = list(
            dict.fromkeys(
                (
                    *tuple(
                        str(item)
                        for item in (
                            state.get(
                                "pending_reactive_dependency_identifiers", ()
                            )
                            or ()
                        )
                    ),
                    *dependency_ids,
                )
            )
        )[-_ACKNOWLEDGED_LIMIT:]

        if base.triggered and base.trigger_key is not None:
            state["last_trigger_reactive_dependency_identifiers"] = list(
                dependency_ids
            )
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="triggered",
                evaluated_at=timestamp,
                triggered=True,
                trigger_key=base.trigger_key,
                reasons=combined_reasons,
                symbol_count=base.symbol_count,
                detail=(
                    "Material market/public evidence and one or more declared "
                    "reactive monitoring dependencies request a canonical CIO "
                    "reassessment."
                ),
            )

        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "revision": int(state.get("baseline_revision", 0) or 0),
                    "reactive_record_identifiers": record_ids,
                    "reactive_dependency_identifiers": dependency_ids,
                    "reasons": combined_reasons,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if state.get("last_trigger_fingerprint") == fingerprint:
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="deduplicated",
                evaluated_at=timestamp,
                reasons=combined_reasons,
                symbol_count=base.symbol_count,
                detail=(
                    "The same reactive monitoring condition already requested a "
                    "canonical CIO reassessment."
                ),
            )

        last_triggered = parse_datetime(state.get("last_triggered_at"))
        if (
            last_triggered is not None
            and timestamp - last_triggered < self.event_cooldown
        ):
            save_json(self.state_path, state)
            return ReassessmentResult(
                state="cooldown",
                evaluated_at=timestamp,
                reasons=combined_reasons,
                symbol_count=base.symbol_count,
                detail=(
                    "Reactive dependency evidence is retained for reassessment "
                    "after the current event-review cooldown."
                ),
            )

        local = timestamp.astimezone(self.timezone)
        trigger_key = (
            f"reactive-evidence-{local.strftime('%Y%m%d-%H%M')}-"
            f"{fingerprint[:12]}"
        )
        state.update(
            {
                "last_triggered_at": timestamp.isoformat(),
                "last_trigger_fingerprint": fingerprint,
                "last_trigger_key": trigger_key,
                "last_trigger_public_record_identifiers": list(record_ids),
                "last_trigger_reactive_dependency_identifiers": list(
                    dependency_ids
                ),
            }
        )
        save_json(self.state_path, state)
        return ReassessmentResult(
            state="triggered",
            evaluated_at=timestamp,
            triggered=True,
            trigger_key=trigger_key,
            reasons=combined_reasons,
            symbol_count=base.symbol_count,
            detail=(
                "Qualified point-in-time evidence matched one or more dependencies "
                "declared by the latest active-investor reactive monitoring plan and "
                "requests a canonical CIO reassessment. The monitoring layer has no "
                "portfolio or execution authority."
            ),
        )

    def acknowledge_assessment(self, *, now: datetime) -> None:
        super().acknowledge_assessment(now=now)
        state = load_json(self.state_path)
        state.pop("pending_reactive_dependency_identifiers", None)
        state.pop("last_trigger_reactive_dependency_identifiers", None)
        save_json(self.state_path, state)


__all__ = ["ReactiveInvestorMaterialCIOReassessmentEngine"]
