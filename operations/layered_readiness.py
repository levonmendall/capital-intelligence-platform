"""Layered, non-authoritative readiness state for the production control plane.

The report separates product serving availability from the stricter evidence,
decision, and execution gates.  It does not grant investment or execution
authority; it only reports whether the existing authorities may be consumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


_LAYER_SCHEMA_VERSION = "capital-intelligence-layered-readiness.v1"


def _aware_utc(value: datetime | None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return resolved.astimezone(timezone.utc)


def _blockers(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


@dataclass(frozen=True, slots=True)
class ReadinessLayer:
    """One observational readiness layer.

    ``ready`` means the named layer's prerequisites are satisfied. Components are
    diagnostic evidence only and cannot authorize a portfolio action.
    """

    name: str
    ready: bool
    blockers: tuple[str, ...] = ()
    components: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": "ready" if self.ready else "blocked",
            "ready": self.ready,
            "blockers": list(self.blockers),
            "components": {name: dict(payload) for name, payload in self.components.items()},
        }


@dataclass(frozen=True, slots=True)
class LayeredReadinessReport:
    """Dependency-closed serving/evidence/decision/execution readiness."""

    generated_at: datetime
    serving: ReadinessLayer
    evidence: ReadinessLayer
    decision: ReadinessLayer
    execution: ReadinessLayer
    schema_version: str = _LAYER_SCHEMA_VERSION
    paper_only: bool = True
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "layers": {
                "serving": self.serving.to_dict(),
                "evidence": self.evidence.to_dict(),
                "decision": self.decision.to_dict(),
                "execution": self.execution.to_dict(),
            },
            "schema_version": self.schema_version,
            "paper_only": True,
            "real_money_authorized": False,
            "downstream_repair_authorized": False,
        }


def compose_layered_readiness(
    *,
    serving_ready: bool,
    evidence_ready: bool,
    decision_ready: bool,
    execution_ready: bool,
    serving_blockers: tuple[str, ...] = (),
    evidence_blockers: tuple[str, ...] = (),
    decision_blockers: tuple[str, ...] = (),
    execution_blockers: tuple[str, ...] = (),
    components: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    generated_at: datetime | None = None,
) -> LayeredReadinessReport:
    """Compose readiness while enforcing one-way prerequisite closure.

    The caller supplies the truth of each layer's own checks.  This function only
    enforces the architecture: evidence depends on serving, decisions depend on
    serving plus evidence, and execution depends on a valid decision-ready state.
    No layer may become ready by repairing or overriding an upstream blocker.
    """

    component_map = components or {}
    serving_ok = bool(serving_ready)
    serving_reasons = _blockers(serving_blockers)
    if not serving_ok and not serving_reasons:
        serving_reasons = ("serving_prerequisite_failed",)

    evidence_ok = serving_ok and bool(evidence_ready)
    evidence_reasons = list(_blockers(evidence_blockers))
    if not serving_ok:
        evidence_reasons.append("serving_not_ready")
    if not evidence_ok and not evidence_reasons:
        evidence_reasons.append("evidence_prerequisite_failed")

    decision_ok = serving_ok and evidence_ok and bool(decision_ready)
    decision_reasons = list(_blockers(decision_blockers))
    if not serving_ok:
        decision_reasons.append("serving_not_ready")
    if not evidence_ok:
        decision_reasons.append("evidence_not_ready")
    if not decision_ok and not decision_reasons:
        decision_reasons.append("decision_prerequisite_failed")

    execution_ok = serving_ok and evidence_ok and decision_ok and bool(execution_ready)
    execution_reasons = list(_blockers(execution_blockers))
    if not serving_ok:
        execution_reasons.append("serving_not_ready")
    if not evidence_ok:
        execution_reasons.append("evidence_not_ready")
    if not decision_ok:
        execution_reasons.append("decision_not_ready")
    if not execution_ok and not execution_reasons:
        execution_reasons.append("execution_prerequisite_failed")

    return LayeredReadinessReport(
        generated_at=_aware_utc(generated_at),
        serving=ReadinessLayer(
            name="SERVING_READY",
            ready=serving_ok,
            blockers=serving_reasons,
            components=component_map.get("serving", {}),
        ),
        evidence=ReadinessLayer(
            name="EVIDENCE_READY",
            ready=evidence_ok,
            blockers=_blockers(evidence_reasons),
            components=component_map.get("evidence", {}),
        ),
        decision=ReadinessLayer(
            name="DECISION_READY",
            ready=decision_ok,
            blockers=_blockers(decision_reasons),
            components=component_map.get("decision", {}),
        ),
        execution=ReadinessLayer(
            name="EXECUTION_READY",
            ready=execution_ok,
            blockers=_blockers(execution_reasons),
            components=component_map.get("execution", {}),
        ),
    )


__all__ = [
    "LayeredReadinessReport",
    "ReadinessLayer",
    "compose_layered_readiness",
]
