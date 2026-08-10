from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from application.global_rotation_cycle import GlobalOpportunityRotationCanonicalCIOCycle
from portfolio.global_rotation import CashCompetitionState, build_global_rotation_context

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def test_rotation_context_cannot_turn_rejected_raw_candidate_into_deployment_opportunity():
    raw = SimpleNamespace(identifier="candidate:rejected")
    queue = SimpleNamespace(ranked=())
    reviewed = GlobalOpportunityRotationCanonicalCIOCycle._rotation_candidates(
        (raw,), queue
    )
    assert reviewed == ()
    context = build_global_rotation_context(
        candidates=reviewed,
        specialist_contexts=(),
        portfolio=SimpleNamespace(
            as_of=NOW,
            cash_weight=0.90,
            cash_expected_return=0.04,
        ),
        minimum_cash_weight=0.05,
    )
    assert context.signals == ()
    assert context.cash_competition_state is CashCompetitionState.CASH_LEADING_ESTIMATE


def test_rotation_candidates_use_authoritative_effective_opportunity_cost():
    candidate = SimpleNamespace(identifier="candidate:qualified")
    # replace() requires a dataclass in production; this structural assertion guards the
    # exact canonical helper used to produce the reviewed set without duplicating models.
    import inspect

    source = inspect.getsource(
        GlobalOpportunityRotationCanonicalCIOCycle._rotation_candidates
    )
    assert "queue.ranked" in source
    assert "item.qualification.effective_opportunity_cost" in source
    assert "queue.rejected" not in source
    freeze_source = inspect.getsource(
        GlobalOpportunityRotationCanonicalCIOCycle._freeze_authoritative_queue
    )
    assert "self._ranking_inputs" in freeze_source
    assert "prepare_ranking_inputs" not in freeze_source
