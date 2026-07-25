"""Tests for point-in-time Decision Replay."""

from __future__ import annotations

import json
from datetime import date, timedelta

from evaluation import (
    DecisionOutcome,
    DecisionQualityReview,
    ProcessVerdict,
)
from monitoring import RegimeMaterialChangeEngine
from reporting import (
    DecisionReplayEvent,
    DecisionReplayPerformance,
    build_decision_replay,
    decision_replay_to_dict,
    render_decision_replay_json,
    render_decision_replay_markdown,
)
from tests.test_material_change_monitoring import (
    ChangedRegimeProvider,
    FIRST_AS_OF,
    SECOND_AS_OF,
    _decision,
    _run,
)


def _replay():
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    current = _run(
        ChangedRegimeProvider(
            growth_value=95.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )
    previous_decision = _decision(previous)
    decision = _decision(current)
    change = RegimeMaterialChangeEngine(clock=lambda: SECOND_AS_OF).compare(
        previous,
        current,
        previous_decision,
        decision,
    )
    performance = DecisionReplayPerformance(
        measured_at=SECOND_AS_OF + timedelta(days=90),
        benchmark="Policy Benchmark",
        decision_return=-0.02,
        benchmark_return=-0.062,
        note="Returns were measured from the decision timestamp.",
    )
    review = DecisionQualityReview(
        decision_identifier=decision.decision_identifier,
        reviewed_at=performance.measured_at,
        process_verdict=ProcessVerdict.DISCIPLINED,
        outcome=DecisionOutcome.POSITIVE,
        process_evidence=("The committee used only released data.",),
        outcome_evidence=(performance.summary,),
        lessons=(
            "The committee identified weakening growth before market consensus.",
        ),
        reviewer="CIO",
    )
    event = DecisionReplayEvent(
        title="Growth report released",
        occurred_at=SECOND_AS_OF - timedelta(hours=4),
        summary="The new release materially weakened the growth signal.",
        evidence_identifiers=("release:INDPRO:2026-02-10",),
    )
    return build_decision_replay(
        event,
        previous,
        current,
        decision,
        change=change,
        performance=performance,
        review=review,
    )


def test_replay_preserves_the_full_reasoning_chain() -> None:
    replay = _replay()

    assert [step.stage for step in replay.steps] == [
        "event",
        "environment",
        "committee",
        "portfolio",
        "outcome",
        "lesson",
    ]
    assert replay.steps[1].headline == "Constructive → Defensive"
    assert "Reduce Risk Assets" in replay.steps[2].headline
    assert replay.relative_return == 0.042
    assert replay.steps[4].headline == (
        "The decision outperformed Policy Benchmark by 4.2%."
    )
    assert "before market consensus" in replay.lesson


def test_replay_schema_labels_hindsight_separately() -> None:
    replay = _replay()
    payload = decision_replay_to_dict(replay)

    assert payload["schema_version"] == "decision-replay.v1"
    assert payload["hindsight_is_separate"] is True
    assert json.loads(render_decision_replay_json(replay)) == payload

    markdown = render_decision_replay_markdown(replay)
    assert markdown.startswith("# Decision Replay")
    assert "Growth report released" in markdown
    assert "Performance and lessons are later observations" in markdown
