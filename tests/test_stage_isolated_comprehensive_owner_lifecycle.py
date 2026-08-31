from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_stage_isolated_evidence_pipeline as pipeline


def _state(*, current_stage="comprehensive_discovery", state="running"):
    return SimpleNamespace(
        pipeline_id="pipeline-1",
        release="release-1",
        state=state,
        generation_id=None,
        evidence_as_of=__import__("datetime").datetime(
            2026, 8, 31, 18, 51, 44, tzinfo=__import__("datetime").timezone.utc
        ),
        stage_started_at=None,
        completed_stages=("reference", "public_live", "us_equity_discovery"),
        current_stage=current_stage,
        next_stage="comprehensive_discovery",
        error_type="ComprehensiveMarketDiscoveryError",
        error_detail="first failure remains attributable",
        path=Path("/tmp/stage-isolated-evidence-latest.json"),
    )


class _Lease:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


def _prepare(monkeypatch, state):
    monkeypatch.setattr(pipeline, "_failed_comprehensive_owner_is_live", lambda values: False)
    monkeypatch.setattr(pipeline, "_ensure_active_attempt", lambda values: state)
    monkeypatch.setattr(pipeline, "load_stage_isolated_evidence_state", lambda values: state)
    monkeypatch.setattr(pipeline, "_safe_failure", lambda **kwargs: None)


def test_live_comprehensive_owner_is_observed_without_expiring_journal(monkeypatch) -> None:
    state = _state()
    _prepare(monkeypatch, state)
    events = []
    monkeypatch.setattr(pipeline, "_acquire_comprehensive_owner", lambda state: None)
    monkeypatch.setattr(pipeline, "_emit_active_stage_owner", lambda state: events.append("active"))
    monkeypatch.setattr(
        pipeline,
        "fail_evidence_stage",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live owner must not fail")),
    )

    assert pipeline.run_pipeline({}) == pipeline._STAGE_ACTIVE_OWNER_RETURN_CODE
    assert events == ["active"]


def test_dead_owner_reaps_descendants_before_freshness_restart_decision(monkeypatch) -> None:
    state = _state()
    _prepare(monkeypatch, state)
    lease = _Lease()
    order = []
    monkeypatch.setattr(pipeline, "_acquire_comprehensive_owner", lambda state: lease)
    monkeypatch.setattr(
        pipeline,
        "_reap_comprehensive_descendants",
        lambda values, state: order.append("reap"),
    )
    monkeypatch.setattr(
        pipeline,
        "_remaining_evidence_lifetime_seconds",
        lambda state, values: 479.0,
    )

    def fail(*args, **kwargs):
        del args, kwargs
        order.append("fail")
        return SimpleNamespace(
            error_type="EvidenceFreshnessExpired",
            error_detail="reserve preserved",
        )

    monkeypatch.setattr(pipeline, "fail_evidence_stage", fail)
    assert pipeline.run_pipeline({}) == pipeline._STAGE_FRESHNESS_EXPIRED_RETURN_CODE
    assert order == ["reap", "fail"]
    assert lease.released is True


def test_failed_comprehensive_child_reaps_descendants_before_owner_release(monkeypatch) -> None:
    state = _state(current_stage=None)
    _prepare(monkeypatch, state)
    lease = _Lease()
    order = []
    monkeypatch.setattr(pipeline, "_acquire_comprehensive_owner", lambda state: lease)
    monkeypatch.setattr(
        pipeline,
        "_run_comprehensive_discovery_cache_reclamation",
        lambda values: None,
    )
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        pipeline,
        "_wait_for_stage_process",
        lambda process, *, state, values: (2, False),
    )
    monkeypatch.setattr(
        pipeline,
        "_reap_comprehensive_descendants",
        lambda values, state: order.append("reap"),
    )

    assert pipeline.run_pipeline({}) == 2
    assert order == ["reap"]
    assert lease.released is True


def test_failed_attempt_is_not_superseded_while_live_owner_holds_lease(monkeypatch) -> None:
    state = _state(state="failed")
    monkeypatch.setattr(pipeline, "load_stage_isolated_evidence_state", lambda values: state)
    monkeypatch.setattr(pipeline, "_acquire_comprehensive_owner", lambda state: None)
    monkeypatch.setattr(pipeline, "_emit_active_stage_owner", lambda state: None)
    monkeypatch.setattr(
        pipeline,
        "_archive_failed_attempt",
        lambda state: (_ for _ in ()).throw(AssertionError("live owner must not be archived")),
    )

    assert pipeline._failed_comprehensive_owner_is_live({}) is True
