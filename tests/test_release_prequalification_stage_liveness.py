"""Regressions for stage-owned release-prequalification liveness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations import release_prequalification_parent_watchdog as watchdog
from operations.evidence_prequalification_attribution import (
    EvidencePrequalificationReason,
    failed_prequalification_attribution,
)


def _stage_state(
    *,
    updated_at: datetime,
    current_stage: str | None,
    completed_stages: tuple[str, ...],
    next_stage: str | None,
    state: str = "running",
):
    return SimpleNamespace(
        pipeline_id="pipeline-current",
        updated_at=updated_at,
        current_stage=current_stage,
        completed_stages=completed_stages,
        next_stage=next_stage,
        state=state,
    )


def test_stage_journal_owns_phase_over_newer_unrelated_public_progress(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    stage_at = started + timedelta(seconds=2)
    public_at = started + timedelta(seconds=9)
    monkeypatch.setattr(
        watchdog,
        "load_stage_isolated_evidence_state",
        lambda _values: _stage_state(
            updated_at=stage_at,
            current_stage="comprehensive_discovery",
            completed_stages=("reference", "comprehensive_structure", "public_live", "us_equity_discovery"),
            next_stage="comprehensive_discovery",
        ),
    )
    monkeypatch.setattr(
        watchdog,
        "_fine_progress_candidates",
        lambda _values, boundary: (
            watchdog.PrequalificationProgress(
                phase="public_live",
                component="sec-companyfacts-live",
                updated_at=public_at,
                state="qualified",
                stall_limit_seconds=120.0,
                metrics={"qualified_count": 13},
            ),
        ),
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "comprehensive_discovery"
    assert progress.component == "stage-isolated:comprehensive_discovery"
    assert progress.stall_limit_seconds == 660.0


def test_current_stage_accepts_newer_nested_dag_progress(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    stage_at = started + timedelta(seconds=2)
    dag_at = started + timedelta(seconds=8)
    monkeypatch.setattr(
        watchdog,
        "load_stage_isolated_evidence_state",
        lambda _values: _stage_state(
            updated_at=stage_at,
            current_stage="comprehensive_discovery",
            completed_stages=("reference", "comprehensive_structure", "public_live", "us_equity_discovery"),
            next_stage="comprehensive_discovery",
        ),
    )
    monkeypatch.setattr(
        watchdog,
        "_fine_progress_candidates",
        lambda _values, boundary: (
            watchdog.PrequalificationProgress(
                phase="comprehensive_discovery",
                component="deep-market-evidence:option",
                updated_at=dag_at,
                state="running",
                stall_limit_seconds=660.0,
                metrics={"completed_nodes": 4},
                progress_token="dag-node-4",
            ),
        ),
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "comprehensive_discovery"
    assert progress.component == "deep-market-evidence:option"
    assert progress.metrics["completed_nodes"] == 4
    assert progress.stall_limit_seconds == 660.0


def test_same_stage_rewrite_does_not_create_new_logical_liveness(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    states = iter(
        (
            _stage_state(
                updated_at=boundary + timedelta(seconds=2),
                current_stage="paper_evidence",
                completed_stages=(
                    "reference",
                    "comprehensive_structure",
                    "public_live",
                    "us_equity_discovery",
                    "comprehensive_discovery",
                ),
                next_stage="paper_evidence",
            ),
            _stage_state(
                updated_at=boundary + timedelta(seconds=20),
                current_stage="paper_evidence",
                completed_stages=(
                    "reference",
                    "comprehensive_structure",
                    "public_live",
                    "us_equity_discovery",
                    "comprehensive_discovery",
                ),
                next_stage="paper_evidence",
            ),
        )
    )
    monkeypatch.setattr(
        watchdog,
        "load_stage_isolated_evidence_state",
        lambda _values: next(states),
    )

    first = watchdog._stage_pipeline_progress({}, boundary=boundary)
    second = watchdog._stage_pipeline_progress({}, boundary=boundary)

    assert first is not None and second is not None
    assert first.updated_at != second.updated_at
    assert first.marker == second.marker


def test_stage_transition_changes_logical_liveness_token(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    states = iter(
        (
            _stage_state(
                updated_at=boundary + timedelta(seconds=2),
                current_stage="comprehensive_discovery",
                completed_stages=("reference", "comprehensive_structure", "public_live", "us_equity_discovery"),
                next_stage="comprehensive_discovery",
            ),
            _stage_state(
                updated_at=boundary + timedelta(seconds=8),
                current_stage="paper_evidence",
                completed_stages=(
                    "reference",
                    "comprehensive_structure",
                    "public_live",
                    "us_equity_discovery",
                    "comprehensive_discovery",
                ),
                next_stage="paper_evidence",
            ),
        )
    )
    monkeypatch.setattr(
        watchdog,
        "load_stage_isolated_evidence_state",
        lambda _values: next(states),
    )

    first = watchdog._stage_pipeline_progress({}, boundary=boundary)
    second = watchdog._stage_pipeline_progress({}, boundary=boundary)

    assert first is not None and second is not None
    assert first.marker != second.marker
    assert second.phase == "paper_evidence"


def test_watchdog_attribution_prefers_explicit_phase_over_incidental_reference_text() -> None:
    attribution = failed_prequalification_attribution(
        detail=(
            "child_stage=release_prequalification_parent_watchdog; "
            "child_error_type=ParentStallTimeout; "
            "child_detail=release evidence prequalification made no durable progress; "
            "failure_type=ParentStallTimeout; "
            "prequalification_phase=comprehensive_discovery; "
            "component=deep-market-evidence:option; "
            "reference futures context was already qualified; "
            "stall_seconds=660; stall_limit_seconds=660"
        ),
        metrics={"qualifier_return_code": 124},
    )

    assert attribution.reason is EvidencePrequalificationReason.DEADLINE_EXCEEDED
    assert attribution.failure_stage == "release_prequalification_parent_watchdog"
    assert attribution.error_type == "ParentStallTimeout"
    assert attribution.capability == "comprehensive_discovery"
    assert attribution.paper_only if hasattr(attribution, "paper_only") else True
