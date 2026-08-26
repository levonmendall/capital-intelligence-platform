from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import run_stage_isolated_evidence_stage as stage_worker
from operations import component_qualified_evidence_maintenance as maintenance


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        evidence_as_of=datetime(2026, 8, 25, 22, 0, tzinfo=timezone.utc),
        reference_manifest_id=None,
        reference_manifest_path=None,
    )


def test_public_live_stage_retries_checkpoint_aware_collector_once(monkeypatch) -> None:
    calls: list[datetime] = []

    def collector(at: datetime):
        calls.append(at)
        if len(calls) == 1:
            raise maintenance._plane.ContinuousEvidencePlaneError("transient provider failure")
        return SimpleNamespace(
            required_sources_ready=True,
            state="available",
            qualified_component_id="public-component-1",
        )

    monkeypatch.setattr(
        maintenance,
        "_component_public_collector",
        lambda _values: collector,
    )

    result = stage_worker._stage_public_live({}, _state())

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert result == {
        "public_live_state": "available",
        "qualified_component_id": "public-component-1",
    }


def test_public_live_stage_fails_closed_after_one_retry(monkeypatch) -> None:
    calls: list[datetime] = []

    def collector(at: datetime):
        calls.append(at)
        raise maintenance._plane.ContinuousEvidencePlaneError("provider still unavailable")

    monkeypatch.setattr(
        maintenance,
        "_component_public_collector",
        lambda _values: collector,
    )

    with pytest.raises(maintenance._plane.ContinuousEvidencePlaneError):
        stage_worker._stage_public_live({}, _state())

    assert len(calls) == 2


def test_public_live_stage_does_not_retry_unexpected_failure(monkeypatch) -> None:
    calls: list[datetime] = []

    def collector(at: datetime):
        calls.append(at)
        raise RuntimeError("corrupt public-live checkpoint")

    monkeypatch.setattr(
        maintenance,
        "_component_public_collector",
        lambda _values: collector,
    )

    with pytest.raises(RuntimeError, match="corrupt public-live checkpoint"):
        stage_worker._stage_public_live({}, _state())

    assert len(calls) == 1
