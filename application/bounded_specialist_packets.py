"""Bounded specialist-packet materialization for the governed CIO runtime.

The production CIO is allowed to evaluate every qualified candidate and retain the
complete append-only evidence record, but it must not keep every full six-specialist
packet resident in RAM at the same time.  This module provides two deliberately
non-authoritative adapters:

* ``RecomputingSpecialistPacketSource`` materializes one preliminary packet on demand
  and never caches the packet object.  A later final CIO pass recomputes the packet
  from the same point-in-time inputs.  Existing bounded historical-learning resolvers
  retain only their compact immutable contexts between those passes.
* ``JournalBackedSpecialistPacketLoader`` reconstructs one already-persisted canonical
  packet at a time for downstream evidence-snapshot capture after construction.

Neither adapter can create candidates, change evidence, change CIO policy, size a
position, authorize construction, or authorize execution.  The cost of the lower
working set is additional deterministic CPU and bounded journal I/O.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from cio import (
    EvidenceDependency,
    EvidenceVetoCategory,
    HistoricalLearningContext,
    HistoricalLearningStatus,
    IndependentSpecialistPacket,
    ScenarioAdjustment,
    SpecialistAnalysis,
    SpecialistPosition,
    SpecialistRole,
)
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal

_LOGGER = logging.getLogger("capital_intelligence.bounded_specialist_packets")


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a list or tuple")
    return tuple(value)


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _current_rss_bytes() -> int | None:
    """Return current process RSS on Linux without importing a monitoring stack."""

    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if not line.startswith("VmRSS:"):
                continue
            fields = line.split()
            if len(fields) >= 2:
                return int(fields[1]) * 1024
    except (OSError, TypeError, ValueError):
        return None
    return None


def _log_boundary(*, stage: str, candidate_identifier: str) -> None:
    rss_bytes = _current_rss_bytes()
    _LOGGER.info(
        "bounded specialist packet boundary stage=%s candidate=%s rss_bytes=%s",
        stage,
        candidate_identifier,
        "unknown" if rss_bytes is None else rss_bytes,
    )


def deserialize_specialist_packet(
    payload: Mapping[str, Any],
) -> IndependentSpecialistPacket:
    """Reconstruct the canonical packet exactly from its v2 journal payload.

    The domain constructors perform the same invariants used during live packet
    creation.  Derived summary fields in the serialized payload are intentionally not
    trusted; they are recomputed from the reconstructed analyses.
    """

    packet_payload = _mapping(payload, field_name="specialist packet payload")
    candidate_identifier = _required_text(
        packet_payload.get("candidate_identifier"),
        field_name="candidate_identifier",
    )
    learning_payload = _mapping(
        packet_payload.get("historical_learning"),
        field_name="historical_learning",
    )
    learning = HistoricalLearningContext(
        candidate_identifier=_required_text(
            learning_payload.get("candidate_identifier"),
            field_name="historical_learning.candidate_identifier",
        ),
        as_of=datetime.fromisoformat(
            _required_text(
                learning_payload.get("as_of"),
                field_name="historical_learning.as_of",
            )
        ),
        status=HistoricalLearningStatus(
            _required_text(
                learning_payload.get("status"),
                field_name="historical_learning.status",
            )
        ),
        source_manifest_identifier=_required_text(
            learning_payload.get("source_manifest_identifier"),
            field_name="historical_learning.source_manifest_identifier",
        ),
        sample_size=learning_payload.get("sample_size"),
        exact_symbol_sample_size=learning_payload.get("exact_symbol_sample_size"),
        regime_matched_sample_size=learning_payload.get("regime_matched_sample_size"),
        horizon_matched_sample_size=learning_payload.get("horizon_matched_sample_size"),
        realized_sample_size=learning_payload.get("realized_sample_size"),
        strict_replay=learning_payload.get("strict_replay"),
        support_rate=learning_payload.get("support_rate"),
        abstention_rate=learning_payload.get("abstention_rate"),
        historical_hit_rate=learning_payload.get("historical_hit_rate"),
        median_historical_confidence=learning_payload.get(
            "median_historical_confidence"
        ),
        median_historical_position_weight=learning_payload.get(
            "median_historical_position_weight"
        ),
        median_realized_return=learning_payload.get("median_realized_return"),
        worst_realized_return=learning_payload.get("worst_realized_return"),
        position_size_multiplier=learning_payload.get("position_size_multiplier"),
        confidence_ceiling=learning_payload.get("confidence_ceiling"),
        summary=_required_text(
            learning_payload.get("summary"),
            field_name="historical_learning.summary",
        ),
        limitations=tuple(
            _sequence(
                learning_payload.get("limitations", ()),
                field_name="historical_learning.limitations",
            )
        ),
        evidence_identifiers=tuple(
            _sequence(
                learning_payload.get("evidence_identifiers", ()),
                field_name="historical_learning.evidence_identifiers",
            )
        ),
        growth_calibration_multiplier=learning_payload.get(
            "growth_calibration_multiplier", 1.0
        ),
        ensemble_calibration_authorized=learning_payload.get(
            "ensemble_calibration_authorized", False
        ),
        subordinate_to_current_evidence=learning_payload.get(
            "subordinate_to_current_evidence", True
        ),
        may_increase_expected_return=learning_payload.get(
            "may_increase_expected_return", False
        ),
        may_increase_confidence=learning_payload.get(
            "may_increase_confidence", False
        ),
        may_increase_position_size=learning_payload.get(
            "may_increase_position_size", False
        ),
        execution_authorized=learning_payload.get("execution_authorized", False),
        policy_promotion_authorized=learning_payload.get(
            "policy_promotion_authorized", False
        ),
    )

    raw_analyses = _sequence(
        packet_payload.get("analyses"),
        field_name="analyses",
    )
    analyses: list[SpecialistAnalysis] = []
    for index, raw_analysis in enumerate(raw_analyses):
        analysis = _mapping(raw_analysis, field_name=f"analyses[{index}]")
        scenario_adjustments = tuple(
            ScenarioAdjustment(
                label=_required_text(
                    adjustment.get("label"),
                    field_name="scenario_adjustment.label",
                ),
                return_delta=adjustment.get("return_delta"),
                probability_delta=adjustment.get("probability_delta"),
                path_drawdown_delta=adjustment.get("path_drawdown_delta"),
            )
            for adjustment in (
                _mapping(item, field_name="scenario_adjustment")
                for item in _sequence(
                    analysis.get("scenario_adjustments", ()),
                    field_name="scenario_adjustments",
                )
            )
        )
        dependencies = tuple(
            EvidenceDependency(
                identifier=_required_text(
                    dependency.get("identifier"),
                    field_name="evidence_dependency.identifier",
                ),
                parent_identifiers=tuple(
                    _sequence(
                        dependency.get("parent_identifiers", ()),
                        field_name="evidence_dependency.parent_identifiers",
                    )
                ),
            )
            for dependency in (
                _mapping(item, field_name="evidence_dependency")
                for item in _sequence(
                    analysis.get("evidence_dependencies", ()),
                    field_name="evidence_dependencies",
                )
            )
        )
        analyses.append(
            SpecialistAnalysis(
                candidate_identifier=candidate_identifier,
                role=SpecialistRole(
                    _required_text(analysis.get("role"), field_name="role")
                ),
                completed_at=datetime.fromisoformat(
                    _required_text(
                        analysis.get("completed_at"),
                        field_name="completed_at",
                    )
                ),
                independent_first_pass=analysis.get("independent_first_pass"),
                position=SpecialistPosition(
                    _required_text(
                        analysis.get("position"),
                        field_name="position",
                    )
                ),
                conclusion=_required_text(
                    analysis.get("conclusion"),
                    field_name="conclusion",
                ),
                expected_return_impact=analysis.get("expected_return_impact"),
                confidence=analysis.get("confidence"),
                supporting_evidence=tuple(
                    _sequence(
                        analysis.get("supporting_evidence", ()),
                        field_name="supporting_evidence",
                    )
                ),
                contradictory_evidence=tuple(
                    _sequence(
                        analysis.get("contradictory_evidence", ()),
                        field_name="contradictory_evidence",
                    )
                ),
                critical_assumptions=tuple(
                    _sequence(
                        analysis.get("critical_assumptions", ()),
                        field_name="critical_assumptions",
                    )
                ),
                risks=tuple(
                    _sequence(analysis.get("risks", ()), field_name="risks")
                ),
                limitations=tuple(
                    _sequence(
                        analysis.get("limitations", ()),
                        field_name="limitations",
                    )
                ),
                change_conditions=tuple(
                    _sequence(
                        analysis.get("change_conditions", ()),
                        field_name="change_conditions",
                    )
                ),
                veto_reasons=tuple(
                    _sequence(
                        analysis.get("veto_reasons", ()),
                        field_name="veto_reasons",
                    )
                ),
                veto_categories=tuple(
                    EvidenceVetoCategory(str(item))
                    for item in _sequence(
                        analysis.get("veto_categories", ()),
                        field_name="veto_categories",
                    )
                ),
                implementation_blocks=tuple(
                    _sequence(
                        analysis.get("implementation_blocks", ()),
                        field_name="implementation_blocks",
                    )
                ),
                recommended_position_weight=analysis.get(
                    "recommended_position_weight"
                ),
                funding_source=analysis.get("funding_source"),
                evidence_origin_identifiers=tuple(
                    _sequence(
                        analysis.get("evidence_origin_identifiers", ()),
                        field_name="evidence_origin_identifiers",
                    )
                ),
                scenario_adjustments=scenario_adjustments,
                evidence_dependencies=dependencies,
            )
        )

    return IndependentSpecialistPacket(
        candidate_identifier=candidate_identifier,
        analyses=tuple(analyses),
        historical_learning=learning,
    )


class RecomputingSpecialistPacketSource:
    """Materialize one packet per lookup and retain no packet cache."""

    def __init__(
        self,
        candidate_identifiers: tuple[str, ...],
        loader: Callable[[str], IndependentSpecialistPacket],
    ) -> None:
        if not isinstance(candidate_identifiers, tuple):
            raise TypeError("candidate_identifiers must be a tuple")
        normalized = tuple(
            _required_text(item, field_name="candidate_identifier")
            for item in candidate_identifiers
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("candidate_identifiers must be unique")
        if not callable(loader):
            raise TypeError("loader must be callable")
        self._candidate_identifiers = frozenset(normalized)
        self._loader = loader

    def get(
        self,
        candidate_identifier: str,
        default: object | None = None,
    ) -> IndependentSpecialistPacket | object | None:
        resolved = _required_text(
            candidate_identifier,
            field_name="candidate_identifier",
        )
        if resolved not in self._candidate_identifiers:
            return default
        _log_boundary(stage="preliminary_packet_before", candidate_identifier=resolved)
        packet = self._loader(resolved)
        if not isinstance(packet, IndependentSpecialistPacket):
            raise TypeError("specialist packet loader returned the wrong type")
        if packet.candidate_identifier != resolved:
            raise ValueError("specialist packet loader returned another candidate")
        _log_boundary(stage="preliminary_packet_after", candidate_identifier=resolved)
        return packet


class JournalBackedSpecialistPacketLoader:
    """Load only the requested current-cycle specialist packet from the CIO journal."""

    def __init__(
        self,
        journal: SQLiteCIOJournal,
        event_identifiers: Mapping[str, str],
    ) -> None:
        if not isinstance(journal, SQLiteCIOJournal):
            raise TypeError("journal must be a SQLiteCIOJournal")
        self._journal = journal
        self._event_identifiers = {
            _required_text(candidate, field_name="candidate_identifier"): _required_text(
                event_identifier,
                field_name="event_identifier",
            )
            for candidate, event_identifier in event_identifiers.items()
        }

    def load(self, candidate_identifier: str) -> IndependentSpecialistPacket:
        resolved = _required_text(
            candidate_identifier,
            field_name="candidate_identifier",
        )
        expected_event_identifier = self._event_identifiers.get(resolved)
        if expected_event_identifier is None:
            raise KeyError(f"no current-cycle specialist packet for {resolved}")
        _log_boundary(stage="snapshot_packet_before", candidate_identifier=resolved)
        event = self._journal.latest(
            aggregate_identifier=resolved,
            event_type=CIOJournalEventType.SPECIALIST_PACKET,
        )
        if event is None:
            raise RuntimeError(
                f"persisted specialist packet is unavailable for {resolved}"
            )
        if event.event_identifier != expected_event_identifier:
            raise RuntimeError(
                "latest specialist packet does not match the current CIO cycle"
            )
        if event.schema_version != "specialist-packet.v2":
            raise RuntimeError("persisted specialist packet schema is unsupported")
        packet = deserialize_specialist_packet(event.payload)
        if packet.candidate_identifier != resolved:
            raise RuntimeError("persisted specialist packet candidate changed")
        _log_boundary(stage="snapshot_packet_after", candidate_identifier=resolved)
        return packet


__all__ = [
    "JournalBackedSpecialistPacketLoader",
    "RecomputingSpecialistPacketSource",
    "deserialize_specialist_packet",
]
