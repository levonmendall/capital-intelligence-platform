from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle


@dataclass(frozen=True)
class _Candidate:
    identifier: str
    opportunity_cost_return: float


def test_rotation_candidates_only_include_authoritatively_ranked_candidates():
    reviewed = _Candidate("candidate:reviewed", 0.02)
    rejected = _Candidate("candidate:rejected", 0.01)
    queue = SimpleNamespace(
        ranked=(
            SimpleNamespace(
                candidate=reviewed,
                qualification=SimpleNamespace(effective_opportunity_cost=0.06),
            ),
        ),
        rejected=(SimpleNamespace(candidate_identifier=rejected.identifier),),
    )

    result = GlobalOpportunityRotationCanonicalCIOCycle._rotation_candidates(
        (reviewed, rejected),
        queue,
    )

    assert tuple(item.identifier for item in result) == (reviewed.identifier,)
    assert result[0].opportunity_cost_return == 0.06


def test_rotation_candidates_preserve_supplied_set_when_queue_is_unavailable():
    candidate = _Candidate("candidate:legacy", 0.03)
    result = GlobalOpportunityRotationCanonicalCIOCycle._rotation_candidates(
        (candidate,),
        None,
    )
    assert result == (candidate,)
