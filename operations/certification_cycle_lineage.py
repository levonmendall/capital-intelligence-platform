"""Durable certification lineage emitted from a completed canonical CIO cycle.

This module consumes only the already-produced canonical cycle result. It does not rerun
screening, specialists, CIO logic, construction, evidence collection, or execution. Its
sole purpose is to bind those authoritative artifacts into the certification state
machine after the canonical executor has completed successfully.
"""

from __future__ import annotations

import hashlib
import json

from operations.certification_runtime_state import (
    advance_linear_state_for_cutoff,
    certification_runtime_enabled,
)
from operations.certification_state_machine import CertificationState


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _decision_material(decision: object) -> dict[str, object]:
    return {
        "candidate_identifier": str(
            getattr(decision, "candidate_identifier", "")
        ),
        "action": _enum_value(getattr(decision, "action", "")),
        "expected_return": getattr(decision, "expected_return", None),
        "recommended_position_weight": getattr(
            decision,
            "recommended_position_weight",
            None,
        ),
        "decision_horizon_days": getattr(decision, "decision_horizon_days", None),
    }


def _snapshot_identity(snapshot: object) -> str:
    for name in ("identifier", "snapshot_identifier", "decision_identifier"):
        value = getattr(snapshot, name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return (
        f"{type(snapshot).__name__}:"
        f"{getattr(snapshot, 'candidate_identifier', '-')}:"
        f"{getattr(snapshot, 'as_of', '-')}"
    )


def certify_completed_cio_cycle(result: object) -> None:
    """Advance committee, CIO, and construction from one canonical completed result."""

    if not certification_runtime_enabled():
        return

    as_of = getattr(result, "as_of", None)
    cycle_id = str(getattr(result, "identifier", "")).strip()
    briefing = getattr(result, "briefing", None)
    briefing_id = str(getattr(briefing, "identifier", "")).strip()
    if as_of is None or not cycle_id or not briefing_id:
        raise RuntimeError("canonical CIO result lacks certification identity")

    evaluations = tuple(getattr(result, "evaluation_snapshots", ()) or ())
    decisions = tuple(getattr(result, "decisions", ()) or ())
    queue = getattr(result, "opportunity_queue", None)
    ranked = tuple(getattr(queue, "ranked", ()) or ())
    rejected = tuple(getattr(queue, "rejected", ()) or ())

    committee_material = {
        "cycle_identifier": cycle_id,
        "opportunity_context_identifier": str(
            getattr(queue, "context_identifier", "")
        ),
        "ranked_candidates": len(ranked),
        "rejected_candidates": len(rejected),
        "evaluation_snapshots": [
            _snapshot_identity(item) for item in evaluations
        ],
    }
    committee_source = "canonical-committee:" + _digest(committee_material)
    advance_linear_state_for_cutoff(
        cutoff=as_of,
        target=CertificationState.COMMITTEE_COMPLETE,
        source_id=committee_source,
        detail="canonical six-specialist committee stage completed",
        metadata={
            "cycle_identifier": cycle_id,
            "evaluation_snapshot_count": len(evaluations),
            "ranked_candidate_count": len(ranked),
            "rejected_candidate_count": len(rejected),
        },
    )

    disposition = getattr(result, "cycle_disposition", None)
    cio_material = {
        "cycle_identifier": cycle_id,
        "decisions": [_decision_material(item) for item in decisions],
        "cycle_disposition": (
            None
            if disposition is None
            else {
                "identifier": str(getattr(disposition, "identifier", "")),
                "status": _enum_value(getattr(disposition, "status", "")),
            }
        ),
        "briefing_identifier": briefing_id,
    }
    cio_source = "canonical-cio:" + _digest(cio_material)
    advance_linear_state_for_cutoff(
        cutoff=as_of,
        target=CertificationState.CIO_COMPLETE,
        source_id=cio_source,
        detail="canonical CIO decision/disposition persisted",
        metadata={
            "cycle_identifier": cycle_id,
            "decision_count": len(decisions),
            "briefing_identifier": briefing_id,
        },
    )

    construction = getattr(result, "construction", None)
    if construction is None:
        construction_source = "canonical-construction:none:" + _digest(
            {
                "cycle_identifier": cycle_id,
                "briefing_identifier": briefing_id,
                "decision_count": len(decisions),
            }
        )
        construction_metadata = {
            "cycle_identifier": cycle_id,
            "construction_present": False,
            "briefing_identifier": briefing_id,
        }
    else:
        request_id = str(
            getattr(construction, "request_identifier", "")
        ).strip()
        if not request_id:
            raise RuntimeError(
                "canonical construction result lacks request identifier"
            )
        construction_source = f"canonical-construction:{request_id}"
        construction_metadata = {
            "cycle_identifier": cycle_id,
            "construction_present": True,
            "request_identifier": request_id,
            "status": _enum_value(getattr(construction, "status", "")),
            "trade_count": len(tuple(getattr(construction, "trades", ()) or ())),
        }

    advance_linear_state_for_cutoff(
        cutoff=as_of,
        target=CertificationState.CONSTRUCTION_COMPLETE,
        source_id=construction_source,
        detail="canonical portfolio construction stage completed",
        metadata=construction_metadata,
    )


__all__ = ["certify_completed_cio_cycle"]
