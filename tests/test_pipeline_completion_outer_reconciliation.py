from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_bounded_continuous_evidence_plane as bounded
from operations import stage_isolated_evidence_pipeline as pipeline


def _completed_state(*, release: str = "release-a") -> SimpleNamespace:
    return SimpleNamespace(
        state="completed",
        completed_stages=pipeline._STAGES,
        generation_id="generation-a",
        pipeline_id="pipeline-a",
        release=release,
    )


def test_outer_worker_reconciles_generic_exit_after_exact_pipeline_completion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(bounded, "_run_isolated_once", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: _completed_state(),
    )

    assert bounded.run_continuous_once(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-a"}
    ) == 0
    output = capsys.readouterr().out
    assert "stage_isolated_evidence_pipeline_exit_reconciled" in output
    assert '"durable_pipeline_completion": true' in output
    assert '"real_money_authorized": false' in output


def test_outer_worker_keeps_incomplete_pipeline_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = SimpleNamespace(
        state="running",
        completed_stages=pipeline._STAGES[:-1],
        generation_id=None,
        pipeline_id="pipeline-a",
        release="release-a",
    )
    monkeypatch.setattr(bounded, "_run_isolated_once", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: incomplete,
    )

    assert bounded.run_continuous_once(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-a"}
    ) == 2


def test_outer_worker_rejects_completed_pipeline_from_other_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bounded, "_run_isolated_once", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: _completed_state(release="release-b"),
    )

    assert bounded.run_continuous_once(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-a"}
    ) == 2


def test_outer_worker_does_not_reconcile_other_return_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bounded, "_run_isolated_once", lambda *args, **kwargs: 3)
    monkeypatch.setattr(
        pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: _completed_state(),
    )

    assert bounded.run_continuous_once(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-a"}
    ) == 3
