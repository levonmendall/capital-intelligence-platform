from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    EvidenceDependency,
    IndependentSpecialistPacket,
    SpecialistAnalysis,
    SpecialistPosition,
    SpecialistRole,
)
from cio.persistence import serialize_specialist_packet

AS_OF = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _analysis(
    role: SpecialistRole,
    *,
    position: SpecialistPosition = SpecialistPosition.SUPPORTIVE,
    confidence: float = 0.80,
    origin: str | None = None,
    parent: str | None = None,
) -> SpecialistAnalysis:
    kwargs: dict[str, object] = {}
    if role is SpecialistRole.PORTFOLIO_RISK:
        kwargs.update(recommended_position_weight=0.05, funding_source="cash")
    dependencies = (
        ()
        if origin is None or parent is None
        else (EvidenceDependency(origin, (parent,)),)
    )
    return SpecialistAnalysis(
        candidate_identifier="candidate:test",
        role=role,
        completed_at=AS_OF + timedelta(minutes=list(SpecialistRole).index(role) + 1),
        independent_first_pass=True,
        position=position,
        conclusion=f"{role.value} conclusion",
        expected_return_impact=0.02,
        confidence=confidence,
        supporting_evidence=(f"support:{role.value}",),
        contradictory_evidence=(),
        critical_assumptions=("Assumption",),
        risks=("Risk",),
        limitations=(),
        change_conditions=("Review",),
        evidence_origin_identifiers=((origin,) if origin else (f"origin:{role.value}",)),
        evidence_dependencies=dependencies,
        **kwargs,
    )


def _packet(*, shared: bool, opposed: bool = False) -> IndependentSpecialistPacket:
    common = "origin:shared" if shared else None
    return IndependentSpecialistPacket(
        candidate_identifier="candidate:test",
        analyses=(
            _analysis(
                SpecialistRole.MACRO_ECONOMIC,
                position=(SpecialistPosition.OPPOSED if opposed else SpecialistPosition.SUPPORTIVE),
                origin=common,
            ),
            _analysis(
                SpecialistRole.MARKET,
                position=(SpecialistPosition.OPPOSED if opposed else SpecialistPosition.SUPPORTIVE),
                origin=common,
            ),
            _analysis(SpecialistRole.CROSS_ASSET_FORECAST),
            _analysis(SpecialistRole.FUNDAMENTAL_VALUATION),
            _analysis(SpecialistRole.PORTFOLIO_RISK),
            _analysis(SpecialistRole.EVIDENCE_GOVERNANCE),
        ),
    )


def test_shared_origin_reduces_effective_directional_count() -> None:
    independent = _packet(shared=False).evidence_independence
    shared = _packet(shared=True).evidence_independence

    assert independent.active_role_count == 4
    assert independent.effective_role_count == pytest.approx(4.0)
    assert shared.effective_role_count == pytest.approx(3.0)
    assert shared.independence_ratio < independent.independence_ratio


def test_dependency_ancestors_create_one_independent_cluster() -> None:
    packet = IndependentSpecialistPacket(
        candidate_identifier="candidate:test",
        analyses=(
            _analysis(
                SpecialistRole.MACRO_ECONOMIC,
                origin="derived:macro",
                parent="origin:policy",
            ),
            _analysis(
                SpecialistRole.MARKET,
                origin="derived:market",
                parent="origin:policy",
            ),
            _analysis(SpecialistRole.CROSS_ASSET_FORECAST),
            _analysis(SpecialistRole.FUNDAMENTAL_VALUATION),
            _analysis(SpecialistRole.PORTFOLIO_RISK),
            _analysis(SpecialistRole.EVIDENCE_GOVERNANCE),
        ),
    )

    assessment = packet.evidence_independence
    assert assessment.effective_role_count == pytest.approx(3.0)
    assert any(
        set(cluster)
        == {SpecialistRole.MACRO_ECONOMIC, SpecialistRole.MARKET}
        for cluster in assessment.cluster_roles
    )


def test_correlated_opposition_counts_once_but_dissent_remains_visible() -> None:
    packet = _packet(shared=True, opposed=True)

    assert packet.independent_opposition_count(0.75) == 1
    assert len(packet.opposing) == 2
    assert packet.strongest_dissent() is not None


def test_packet_serialization_persists_independence_diagnostics() -> None:
    payload = serialize_specialist_packet(_packet(shared=True), code_version="test")

    assert payload["effective_directional_count"] == pytest.approx(3.0)
    assert payload["evidence_independence_ratio"] == pytest.approx(0.75)
    assert payload["independent_cluster_count"] == 3
