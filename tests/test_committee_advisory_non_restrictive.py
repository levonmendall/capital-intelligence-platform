from __future__ import annotations

import json
from dataclasses import replace

import cio.committee_advisory_cio as advisory_cio_module
from cio import IndependentSpecialistPacket, RecommendationUniversePolicy
from cio.committee_advisory import build_committee_advisory_report
from cio.committee_advisory_cio import ChiefInvestmentOfficer as AdvisoryCIO
from cio.compounding_authority import CompoundingChiefInvestmentOfficer
from cio.decision_integrity import ChiefInvestmentOfficer as BaselineCIO
from cio.models import SpecialistPosition, SpecialistRole
from tests.cio_test_fixtures import build_candidate, build_specialist_packet


def _advisory_payload(decision) -> dict[str, object]:
    record = next(
        item
        for item in decision.monitoring_indicators
        if item.startswith("committee-advisory.v1:")
    )
    return json.loads(record.split(":", 1)[1])


def test_advisory_cio_preserves_authoritative_action_and_size() -> None:
    candidate = build_candidate()
    packet = build_specialist_packet(candidate)
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    baseline = BaselineCIO().synthesize(candidate, universe, packet)
    advisory = AdvisoryCIO().synthesize(candidate, universe, packet)

    assert advisory.action is baseline.action
    assert advisory.recommended_position_weight == baseline.recommended_position_weight
    assert advisory.expected_return == baseline.expected_return
    assert advisory.evidence_vetoes == baseline.evidence_vetoes
    assert advisory.implementation_blocks == baseline.implementation_blocks
    payload = _advisory_payload(advisory)
    assert payload["advisory_only"] is True
    assert payload["can_veto_action"] is False
    assert payload["can_change_candidate_qualification"] is False
    assert payload["can_remove_candidate"] is False
    assert payload["can_change_position_size"] is False
    assert payload["can_change_policy_thresholds"] is False


def test_advisory_failure_is_fail_open_and_cannot_suppress_candidate(monkeypatch) -> None:
    candidate = build_candidate()
    packet = build_specialist_packet(candidate)
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)
    baseline = BaselineCIO().synthesize(candidate, universe, packet)

    def fail_advisory(*args, **kwargs):
        raise RuntimeError("synthetic advisory failure")

    monkeypatch.setattr(
        advisory_cio_module,
        "build_committee_advisory_report",
        fail_advisory,
    )
    advisory = AdvisoryCIO().synthesize(candidate, universe, packet)

    assert advisory.action is baseline.action
    assert advisory.recommended_position_weight == baseline.recommended_position_weight
    assert advisory.expected_return == baseline.expected_return
    payload = _advisory_payload(advisory)
    assert payload["status"] == "unavailable"
    assert payload["can_remove_candidate"] is False
    assert payload["can_change_position_size"] is False


def test_disagreement_overlap_and_input_depth_are_explicit_not_gates() -> None:
    candidate = build_candidate()
    original = build_specialist_packet(candidate)
    analyses = list(original.analyses)
    shared_assumption = "Demand normalization occurs within the decision horizon"

    macro_index = next(
        index
        for index, item in enumerate(analyses)
        if item.role is SpecialistRole.MACRO_ECONOMIC
    )
    market_index = next(
        index
        for index, item in enumerate(analyses)
        if item.role is SpecialistRole.MARKET
    )
    analyses[macro_index] = replace(
        analyses[macro_index],
        critical_assumptions=(shared_assumption,),
        evidence_origin_identifiers=("origin:shared-macro-market",),
    )
    analyses[market_index] = replace(
        analyses[market_index],
        position=SpecialistPosition.OPPOSED,
        conclusion="Market trend is vulnerable to a failed breakout",
        contradictory_evidence=("Breadth has narrowed",),
        critical_assumptions=(shared_assumption,),
        evidence_origin_identifiers=("origin:shared-macro-market",),
    )
    packet = IndependentSpecialistPacket(
        candidate_identifier=candidate.identifier,
        analyses=tuple(analyses),
        historical_learning=original.historical_learning,
    )

    report = build_committee_advisory_report(candidate, packet)
    payload = report.to_dict()
    disagreement = payload["disagreement"]

    assert len(packet.analyses) == 6
    assert SpecialistRole.MARKET in report.disagreement.opposing_roles
    assert shared_assumption in report.disagreement.shared_assumptions
    assert report.disagreement.evidence_independence_ratio < 1.0
    assert len(report.disagreement.input_depth) == 6
    assert payload["can_veto_action"] is False
    assert payload["can_change_candidate_qualification"] is False
    assert payload["can_remove_candidate"] is False
    assert payload["can_change_position_size"] is False
    assert disagreement["advisory_only"] is True


def test_production_compounding_cio_inherits_advisory_boundary() -> None:
    assert issubclass(CompoundingChiefInvestmentOfficer, AdvisoryCIO)
