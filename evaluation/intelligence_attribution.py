"""Runtime-observed intelligence attribution for completed canonical CIO cycles.

This module is diagnostic-only.  It consumes already-persisted committee/CIO
information traces after canonical execution and cannot alter evidence,
specialist conclusions, CIO decisions, construction, sizing, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from cio import SpecialistRole
from cio.persistence import CIOJournalEvent, CIOJournalEventType, SQLiteCIOJournal
from evaluation.committee_cio_trace import CommitteeCIOInformationTrace


_SCHEMA_VERSION = "intelligence-attribution.v1-runtime-observed"
_MATERIAL_INFLUENCE_UNKNOWN = "not_counterfactually_observable"

_REQUIRED_SPECIALIST_ROLES = frozenset(
    {
        SpecialistRole.MACRO_ECONOMIC.value,
        SpecialistRole.MARKET.value,
        SpecialistRole.CROSS_ASSET_FORECAST.value,
        SpecialistRole.FUNDAMENTAL_VALUATION.value,
        SpecialistRole.PORTFOLIO_RISK.value,
        SpecialistRole.EVIDENCE_GOVERNANCE.value,
    }
)

# Marker matching is intentionally narrow.  A capability is never marked
# observed merely because implementation code exists.
_CAPABILITIES: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("point_in_time_capital_flow", ("derived-capital-flow", "point-in-time-capital-flow")),
    ("predictive_market_intelligence", ("predictive-market-intelligence",)),
    ("phase5_forward_intelligence", ("phase5-forward-intelligence", "phase-5-forward-intelligence")),
    ("certified_forward_research", ("certified-forward-research",)),
    ("governed_event_forward", ("governed-event-forward",)),
    ("global_opportunity_radar", ("global-opportunity-radar",)),
    ("persistent_opportunity_sweep", ("persistent-opportunity-sweep",)),
    ("canonical_exposure_graph", ("canonical-exposure-graph",)),
    # These capabilities currently do not expose a unique, candidate-level
    # runtime lineage marker in the post-decision trace.  Reporting them as
    # invocation_not_observable is more truthful than inferring execution.
    ("mispriced_change", None),
    ("theme_successor", None),
    ("global_leadership_economics", None),
    ("candidate_risk_intelligence", None),
    ("joint_candidate_intelligence", None),
    ("six_specialist_committee", ()),
    ("global_compound_optimizer", None),
)

_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "token=",
    "authorization",
    "bearer ",
    "secret",
    "password",
)


def _normalized(value: object) -> str:
    return str(value).strip().lower().replace("_", "-").replace(" ", "-")


def _safe_identifier(value: object) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return None
    return text[:240]


def _safe_unique(values: Sequence[object], *, limit: int = 16) -> tuple[str, ...]:
    safe: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _safe_identifier(value)
        if item is None or item in seen:
            continue
        seen.add(item)
        safe.append(item)
        if len(safe) >= limit:
            break
    return tuple(safe)


def _matches(value: object, markers: tuple[str, ...]) -> bool:
    normalized = _normalized(value)
    return any(marker in normalized for marker in markers)


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class CapabilityAttribution:
    capability: str
    declared: bool
    invocation_state: str
    evidence_produced: bool
    evidence_identifiers: tuple[str, ...]
    model_versions: tuple[str, ...]
    candidate_identifiers: tuple[str, ...]
    specialist_roles_consuming: tuple[str, ...]
    reached_cio: bool
    material_decision_influence: str = _MATERIAL_INFLUENCE_UNKNOWN
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "declared": self.declared,
            "invocation_state": self.invocation_state,
            "evidence_produced": self.evidence_produced,
            "evidence_identifiers": list(self.evidence_identifiers),
            "model_versions": list(self.model_versions),
            "candidate_identifiers": list(self.candidate_identifiers),
            "specialist_roles_consuming": list(self.specialist_roles_consuming),
            "reached_cio": self.reached_cio,
            "material_decision_influence": self.material_decision_influence,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class CycleIntelligenceAttribution:
    cycle_identifier: str
    as_of: datetime
    capabilities: tuple[CapabilityAttribution, ...]
    candidate_count: int
    schema_version: str = _SCHEMA_VERSION

    @property
    def declared_capability_count(self) -> int:
        return sum(item.declared for item in self.capabilities)

    @property
    def observed_invocation_count(self) -> int:
        return sum(item.invocation_state == "observed" for item in self.capabilities)

    @property
    def evidence_producing_count(self) -> int:
        return sum(item.evidence_produced for item in self.capabilities)

    @property
    def specialist_consumed_count(self) -> int:
        return sum(bool(item.specialist_roles_consuming) for item in self.capabilities)

    @property
    def reached_cio_count(self) -> int:
        return sum(item.reached_cio for item in self.capabilities)

    @property
    def unobserved_capabilities(self) -> tuple[str, ...]:
        return tuple(
            item.capability
            for item in self.capabilities
            if item.invocation_state != "observed"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_kind": "cycle_intelligence_attribution",
            "cycle_identifier": self.cycle_identifier,
            "as_of": self.as_of.isoformat(),
            "candidate_count": self.candidate_count,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "aggregate": {
                "declared_capability_count": self.declared_capability_count,
                "observed_invocation_count": self.observed_invocation_count,
                "evidence_producing_count": self.evidence_producing_count,
                "specialist_consumed_count": self.specialist_consumed_count,
                "reached_cio_count": self.reached_cio_count,
                "unobserved_capabilities": list(self.unobserved_capabilities),
            },
            "authority": {
                "decision_authority": False,
                "construction_authority": False,
                "sizing_authority": False,
                "execution_authority": False,
                "allocation_authority": False,
                "paper_only": True,
            },
        }


def build_cycle_intelligence_attribution(
    *,
    cycle_identifier: str,
    as_of: datetime,
    traces: Sequence[CommitteeCIOInformationTrace],
) -> CycleIntelligenceAttribution:
    """Attribute only capabilities directly observable in completed traces."""

    if not isinstance(cycle_identifier, str) or not cycle_identifier.strip():
        raise ValueError("cycle_identifier must be a non-empty string")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    trace_rows: list[dict[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, CommitteeCIOInformationTrace):
            raise TypeError("traces must contain CommitteeCIOInformationTrace records")
        payload = trace.payload
        source = _as_mapping(payload.get("source"))
        specialists = tuple(
            item
            for item in payload.get("specialists", ())
            if isinstance(item, Mapping)
        )
        cio_decision = _as_mapping(payload.get("cio_decision"))
        trace_rows.append(
            {
                "candidate_identifier": str(payload.get("candidate_identifier", "")),
                "candidate_evidence": tuple(source.get("candidate_evidence_identifiers", ())),
                "specialists": specialists,
                "cio_present": bool(cio_decision.get("action")),
            }
        )

    attributions: list[CapabilityAttribution] = []
    for capability, markers in _CAPABILITIES:
        if capability == "six_specialist_committee":
            candidate_ids: list[str] = []
            specialist_roles: set[str] = set()
            reached_cio = False
            for row in trace_rows:
                roles = {
                    str(item.get("role"))
                    for item in row["specialists"]
                    if item.get("role")
                }
                if _REQUIRED_SPECIALIST_ROLES.issubset(roles):
                    candidate_ids.append(row["candidate_identifier"])
                    specialist_roles.update(_REQUIRED_SPECIALIST_ROLES)
                    reached_cio = reached_cio or bool(row["cio_present"])
            observed = bool(candidate_ids)
            attributions.append(
                CapabilityAttribution(
                    capability=capability,
                    declared=True,
                    invocation_state="observed" if observed else "not_observed",
                    evidence_produced=False,
                    evidence_identifiers=(),
                    model_versions=(),
                    candidate_identifiers=_safe_unique(candidate_ids),
                    specialist_roles_consuming=tuple(sorted(specialist_roles)),
                    reached_cio=reached_cio,
                    role="advisory",
                )
            )
            continue

        if markers is None:
            attributions.append(
                CapabilityAttribution(
                    capability=capability,
                    declared=True,
                    invocation_state="invocation_not_observable",
                    evidence_produced=False,
                    evidence_identifiers=(),
                    model_versions=(),
                    candidate_identifiers=(),
                    specialist_roles_consuming=(),
                    reached_cio=False,
                    role=None,
                )
            )
            continue

        evidence_ids: list[object] = []
        candidate_ids: list[object] = []
        consumer_roles: set[str] = set()
        reached_cio = False
        for row in trace_rows:
            matched_candidate_evidence = tuple(
                item for item in row["candidate_evidence"] if _matches(item, markers)
            )
            matched_norm = {_normalized(item) for item in matched_candidate_evidence}
            if matched_candidate_evidence:
                evidence_ids.extend(matched_candidate_evidence)
                candidate_ids.append(row["candidate_identifier"])
            row_consumers: set[str] = set()
            for specialist in row["specialists"]:
                role = str(specialist.get("role", ""))
                origins = tuple(specialist.get("evidence_origin_identifiers", ()))
                if any(
                    _matches(origin, markers) or _normalized(origin) in matched_norm
                    for origin in origins
                ):
                    row_consumers.add(role)
            if row_consumers:
                consumer_roles.update(row_consumers)
                reached_cio = reached_cio or bool(row["cio_present"])

        safe_evidence = _safe_unique(evidence_ids)
        observed = bool(evidence_ids)
        attributions.append(
            CapabilityAttribution(
                capability=capability,
                declared=True,
                invocation_state="observed" if observed else "not_observed",
                evidence_produced=observed,
                evidence_identifiers=safe_evidence,
                model_versions=(),
                candidate_identifiers=_safe_unique(candidate_ids),
                specialist_roles_consuming=tuple(sorted(consumer_roles)),
                reached_cio=reached_cio,
                role="advisory",
            )
        )

    return CycleIntelligenceAttribution(
        cycle_identifier=cycle_identifier.strip(),
        as_of=as_of,
        capabilities=tuple(attributions),
        candidate_count=len(trace_rows),
    )


def append_cycle_intelligence_attribution(
    journal: SQLiteCIOJournal,
    attribution: CycleIntelligenceAttribution,
) -> CIOJournalEvent:
    """Append one deterministic diagnostic record for the completed cycle."""

    return journal.append(
        event_type=CIOJournalEventType.COMMITTEE_CIO_INFORMATION_TRACE,
        aggregate_identifier=attribution.cycle_identifier,
        occurred_at=attribution.as_of,
        payload=attribution.to_dict(),
        schema_version=attribution.schema_version,
        event_identifier=(
            f"event:intelligence-attribution:{attribution.cycle_identifier}"
        ),
    )


__all__ = [
    "CapabilityAttribution",
    "CycleIntelligenceAttribution",
    "append_cycle_intelligence_attribution",
    "build_cycle_intelligence_attribution",
]
