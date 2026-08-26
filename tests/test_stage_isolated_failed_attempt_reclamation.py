from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import run_stage_isolated_evidence_pipeline as pipeline


def _attempt(*, state: str, pipeline_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        state=state,
        pipeline_id=pipeline_id,
        current_stage="public_live",
        completed_stages=("reference",),
        evidence_as_of=datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc),
        generation_id=None,
    )


def test_failed_attempt_reclaims_after_archive_before_replacement(monkeypatch) -> None:
    previous = _attempt(state="failed", pipeline_id="failed-attempt")
    replacement = _attempt(state="running", pipeline_id="fresh-attempt")
    order: list[str] = []

    monkeypatch.setattr(pipeline, "load_stage_isolated_evidence_state", lambda _values: previous)
    monkeypatch.setattr(
        pipeline,
        "_archive_failed_attempt",
        lambda _state: order.append("archive") or Path("attempt.json"),
    )
    monkeypatch.setattr(
        pipeline,
        "_run_failed_attempt_cache_reclamation",
        lambda _values: order.append("reclaim"),
    )
    monkeypatch.setattr(
        pipeline,
        "ensure_stage_isolated_evidence_pipeline",
        lambda _values: order.append("replace") or replacement,
    )

    assert pipeline._ensure_active_attempt({}) is replacement
    assert order == ["archive", "reclaim", "replace"]


def test_nonfailed_attempt_does_not_reclaim_failed_attempt_cache(monkeypatch) -> None:
    existing = _attempt(state="running", pipeline_id="active-attempt")
    calls: list[str] = []

    monkeypatch.setattr(pipeline, "load_stage_isolated_evidence_state", lambda _values: existing)
    monkeypatch.setattr(
        pipeline,
        "_run_failed_attempt_cache_reclamation",
        lambda _values: calls.append("reclaim"),
    )
    monkeypatch.setattr(pipeline, "ensure_stage_isolated_evidence_pipeline", lambda _values: existing)

    assert pipeline._ensure_active_attempt({}) is existing
    assert calls == []


def test_failed_attempt_reclamation_uses_broad_advisory_reclaimer(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def capture(values, *, stage, event, code, capture_report=False):
        calls.append(
            {
                "values": values,
                "stage": stage,
                "event": event,
                "code": code,
                "capture_report": capture_report,
            }
        )

    monkeypatch.setattr(pipeline, "_run_completed_evidence_cache_reclamation", capture)
    values = {"RENDER": "true"}

    pipeline._run_failed_attempt_cache_reclamation(values)

    assert calls == [
        {
            "values": values,
            "stage": "attempt_supersession",
            "event": pipeline._FAILED_ATTEMPT_CACHE_RECLAMATION_EVENT,
            "code": pipeline._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE,
            "capture_report": True,
        }
    ]


def test_reclamation_preserves_fresh_canonical_attempt_creation(monkeypatch) -> None:
    previous = _attempt(state="failed", pipeline_id="failed-attempt")
    replacement = _attempt(state="running", pipeline_id="fresh-attempt")
    ensure_calls: list[object] = []

    monkeypatch.setattr(pipeline, "load_stage_isolated_evidence_state", lambda _values: previous)
    monkeypatch.setattr(pipeline, "_archive_failed_attempt", lambda _state: Path("attempt.json"))
    monkeypatch.setattr(pipeline, "_run_failed_attempt_cache_reclamation", lambda _values: None)

    def ensure(values):
        ensure_calls.append(values)
        return replacement

    monkeypatch.setattr(pipeline, "ensure_stage_isolated_evidence_pipeline", ensure)

    assert pipeline._ensure_active_attempt({"sentinel": "value"}) is replacement
    assert ensure_calls == [{"sentinel": "value"}]
    assert replacement.pipeline_id != previous.pipeline_id
