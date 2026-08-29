from __future__ import annotations

import subprocess
from datetime import datetime, timezone

import pytest

from operations import bounded_comprehensive_discovery_spool as bounded
from operations import comprehensive_discovery_input_spool as legacy
from operations import epoch_scoped_provider_acquisition as fanout
from operations import stage_isolated_evidence_pipeline as pipeline
import run_stage_isolated_evidence_pipeline as runtime


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-comprehensive-epoch-guard",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def _running_comprehensive(values: dict[str, str], tmp_path):
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values)
    for stage in ("reference", "public_live", "us_equity_discovery"):
        state = pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
        )
        state = pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
            reference_manifest_id=("manifest-1" if stage == "reference" else None),
            reference_manifest_path=(
                str(tmp_path / "manifest.json") if stage == "reference" else None
            ),
        )
    state = pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="comprehensive_discovery",
    )
    assert state.current_stage == "comprehensive_discovery"
    assert state.next_stage == "comprehensive_discovery"
    return state


def test_same_epoch_comprehensive_restart_fails_before_reclamation_or_spawn(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    state = _running_comprehensive(values, tmp_path)

    monkeypatch.setattr(
        runtime,
        "_remaining_evidence_lifetime_seconds",
        lambda _state, _values: 95.0,
    )

    def forbidden_reclamation(_values):  # pragma: no cover - assertion helper
        raise AssertionError("stale comprehensive restart must fail before reclamation")

    def forbidden_spawn(*_args, **_kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("stale comprehensive restart must fail before child spawn")

    monkeypatch.setattr(
        runtime,
        "_run_comprehensive_discovery_cache_reclamation",
        forbidden_reclamation,
    )
    monkeypatch.setattr(runtime.subprocess, "Popen", forbidden_spawn)

    assert runtime.run_pipeline(values) == runtime._STAGE_FRESHNESS_EXPIRED_RETURN_CODE

    latest = pipeline.load_stage_isolated_evidence_state(values)
    assert latest is not None
    assert latest.pipeline_id == state.pipeline_id
    assert latest.state == "failed"
    assert latest.current_stage == "comprehensive_discovery"
    assert latest.error_type == "EvidenceFreshnessExpired"
    assert "restart refused" in str(latest.error_detail)
    assert "remaining_seconds=95.000" in str(latest.error_detail)
    assert "required_remaining_seconds=480" in str(latest.error_detail)
    assert latest.completed_stages == (
        "reference",
        "public_live",
        "us_equity_discovery",
    )


def test_comprehensive_restart_guard_preserves_existing_budget_invariants() -> None:
    from operations import continuous_evidence_plane as plane

    assert runtime._COMPREHENSIVE_DISCOVERY_RESTART_RESERVE_SECONDS == 480.0
    assert runtime._COMPREHENSIVE_DISCOVERY_RESTART_RESERVE_SECONDS == (
        fanout._DOWNSTREAM_RESERVE_SECONDS
    )
    assert fanout._MAX_FANOUT_SECONDS == 300.0
    assert plane._DEFAULT_MAX_AGE_SECONDS == 900.0
    assert fanout._MAX_WORKERS == 6


def test_canonical_publication_wait_uses_existing_epoch_provider_budget(
    tmp_path, monkeypatch
) -> None:
    request_path = tmp_path / "request.json"
    waits: list[float | None] = []

    class CompletedProcess:
        def wait(self, timeout=None):
            waits.append(timeout)
            return 0

        def poll(self):
            return 0

        def terminate(self):  # pragma: no cover - success path
            raise AssertionError("completed publication must not be terminated")

        def kill(self):  # pragma: no cover - success path
            raise AssertionError("completed publication must not be killed")

    monkeypatch.setattr(
        bounded,
        "_provider_publication_timeout_seconds",
        lambda _path, _values: 12.5,
    )
    monkeypatch.setattr(
        bounded.subprocess,
        "Popen",
        lambda *_args, **_kwargs: CompletedProcess(),
    )

    bounded._run_stage("publication", request_path, {})

    assert waits == [12.5]


def test_canonical_publication_timeout_terminates_child_and_fails_closed(
    tmp_path, monkeypatch
) -> None:
    request_path = tmp_path / "request.json"

    class TimedOutProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False
            self.waits: list[float | None] = []

        def wait(self, timeout=None):
            self.waits.append(timeout)
            if self.terminated:
                return -15
            if self.killed:
                return -9
            raise subprocess.TimeoutExpired("provider-publication", timeout)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    child = TimedOutProcess()
    monkeypatch.setattr(
        bounded,
        "_provider_publication_timeout_seconds",
        lambda _path, _values: 7.5,
    )
    monkeypatch.setattr(
        bounded.subprocess,
        "Popen",
        lambda *_args, **_kwargs: child,
    )

    with pytest.raises(
        legacy.ComprehensiveDiscoverySpoolError,
        match="exceeded the existing epoch-scoped provider acquisition window",
    ):
        bounded._run_stage("publication", request_path, {})

    assert child.terminated is True
    assert child.killed is False
    assert child.waits == [7.5, bounded._PUBLICATION_TERMINATION_GRACE_SECONDS]


def test_canonical_publication_does_not_spawn_without_provider_window(
    tmp_path, monkeypatch
) -> None:
    request_path = tmp_path / "request.json"
    monkeypatch.setattr(
        bounded,
        "_provider_publication_timeout_seconds",
        lambda _path, _values: 0.0,
    )

    def forbidden_spawn(*_args, **_kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("publication must not start inside the downstream reserve")

    monkeypatch.setattr(bounded.subprocess, "Popen", forbidden_spawn)

    with pytest.raises(
        legacy.ComprehensiveDiscoverySpoolError,
        match="has no provider-acquisition time beyond the downstream reserve",
    ):
        bounded._run_stage("publication", request_path, {})


def test_canonical_publication_budget_reuses_fanout_calculation(
    tmp_path, monkeypatch
) -> None:
    request_path = tmp_path / "request.json"
    epoch = datetime(2026, 8, 29, 1, 26, 42, tzinfo=timezone.utc)
    observed: list[tuple[datetime, dict[str, str]]] = []

    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": epoch.isoformat()}, object()),
    )
    monkeypatch.setattr(
        legacy,
        "_parse_timestamp",
        lambda _value, field_name: epoch,
    )

    def existing_budget(decision_epoch, values, *, now=None):
        assert now is None
        observed.append((decision_epoch, dict(values)))
        return 123.0

    monkeypatch.setattr(fanout, "_fanout_budget_seconds", existing_budget)

    values = {"RENDER": "true", "UNCHANGED": "1"}
    assert bounded._provider_publication_timeout_seconds(request_path, values) == 123.0
    assert observed == [(epoch, values)]
