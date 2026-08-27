from __future__ import annotations

import inspect
import os
import signal
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from operations import comprehensive_discovery_input_spool as legacy
from operations import continuous_evidence_plane as evidence_plane
from operations import transactional_lane_comprehensive_discovery_coordinator as coordinator


def test_remaining_epoch_uses_existing_900_second_freshness_contract() -> None:
    decision_epoch = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)
    now = decision_epoch + timedelta(seconds=850)

    assert evidence_plane._DEFAULT_MAX_AGE_SECONDS == 900.0
    assert coordinator._remaining_epoch_seconds(
        decision_epoch=decision_epoch,
        values={},
        now=now,
    ) == pytest.approx(50.0)

    source = inspect.getsource(coordinator)
    assert "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS" not in source


def test_expired_epoch_refuses_to_spawn_lane(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        coordinator,
        "_record_transaction_start",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(coordinator, "_remaining_epoch_seconds", lambda **kwargs: 0.0)

    def fail_spawn(*args, **kwargs):
        raise AssertionError("expired evidence must not spawn a lane child")

    monkeypatch.setattr(coordinator.subprocess, "Popen", fail_spawn)

    with pytest.raises(
        legacy.ComprehensiveDiscoverySpoolError,
        match="refused expired evidence epoch",
    ):
        coordinator._run_lane_transaction(
            tmp_path / "request.json",
            {"CAPITAL_INTELLIGENCE_RELEASE": "release-1"},
            asset_class="fx",
            index=0,
            decision_epoch=datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc),
        )


def test_timeout_terminates_child_tree_and_never_loads_timed_out_state(
    monkeypatch,
    tmp_path,
) -> None:
    class TimedOutProcess:
        pid = 12345

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="lane", timeout=timeout)

        def poll(self):
            return None

    process = TimedOutProcess()
    popen_kwargs = {}
    terminations = []

    def fake_popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(
        coordinator,
        "_record_transaction_start",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(coordinator, "_remaining_epoch_seconds", lambda **kwargs: 0.01)
    monkeypatch.setattr(coordinator.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        coordinator,
        "_terminate_process_tree",
        lambda candidate, **kwargs: terminations.append(candidate) or (True, True),
    )
    monkeypatch.setattr(coordinator, "_process_tree_alive", lambda candidate: False)
    monkeypatch.setattr(
        coordinator._bounded,
        "_load_stage_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("timed-out state must never be loaded")
        ),
    )

    with pytest.raises(
        legacy.ComprehensiveDiscoverySpoolError,
        match="exceeded the existing evidence freshness epoch",
    ):
        coordinator._run_lane_transaction(
            tmp_path / "request.json",
            {"CAPITAL_INTELLIGENCE_RELEASE": "release-1"},
            asset_class="fx",
            index=0,
            decision_epoch=datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc),
        )

    assert terminations == [process]
    assert popen_kwargs["start_new_session"] is (os.name == "posix")


def test_process_tree_termination_escalates_to_sigkill_and_reaps(monkeypatch) -> None:
    class Process:
        pid = 12345

        def __init__(self):
            self.waits = []

        def wait(self, timeout=None):
            self.waits.append(timeout)
            return -signal.SIGKILL

    process = Process()
    signals = []
    alive = iter((True, True, True))

    monkeypatch.setattr(
        coordinator,
        "_process_tree_alive",
        lambda candidate: next(alive, False),
    )
    monkeypatch.setattr(
        coordinator,
        "_signal_process_tree",
        lambda candidate, sig: signals.append(sig),
    )

    terminated, killed = coordinator._terminate_process_tree(
        process,
        grace_seconds=0.0,
    )

    assert terminated is True
    assert killed is True
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert process.waits


def test_posix_signal_targets_process_group(monkeypatch) -> None:
    if os.name != "posix":
        pytest.skip("process groups are POSIX-only")

    class Process:
        pid = 43210

        def poll(self):
            return None

    calls = []
    monkeypatch.setattr(
        coordinator.os,
        "killpg",
        lambda pid, sig: calls.append((pid, sig)),
    )

    coordinator._signal_process_tree(Process(), signal.SIGTERM)

    assert calls == [(43210, signal.SIGTERM)]


def test_fresh_retry_can_start_after_timed_out_attempt(monkeypatch, tmp_path) -> None:
    class TimedOutProcess:
        pid = 10001

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="lane", timeout=timeout)

        def poll(self):
            return None

    class SuccessfulProcess:
        pid = 10002

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    processes = iter((TimedOutProcess(), SuccessfulProcess()))
    spawned = []

    def fake_popen(*args, **kwargs):
        process = next(processes)
        spawned.append(process)
        return process

    state = {
        "schema_version": coordinator._transaction._TRANSACTION_SCHEMA,
        "transactional_lane_compaction": True,
        "raw_catalog_persisted": False,
        "asset_class": "fx",
        "raw_record_count": 1,
        "record_count": 1,
        "peak_rss_bytes": 0,
    }

    monkeypatch.setattr(
        coordinator,
        "_record_transaction_start",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(coordinator, "_remaining_epoch_seconds", lambda **kwargs: 1.0)
    monkeypatch.setattr(coordinator.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        coordinator,
        "_terminate_process_tree",
        lambda *args, **kwargs: (True, True),
    )
    monkeypatch.setattr(coordinator, "_process_tree_alive", lambda process: False)
    monkeypatch.setattr(
        coordinator._bounded,
        "_load_stage_state",
        lambda *args, **kwargs: state,
    )
    monkeypatch.setattr(
        coordinator,
        "run_post_lane_cache_reclamation",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        coordinator,
        "_publish_transaction_completion",
        lambda **kwargs: None,
    )

    decision_epoch = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)
    with pytest.raises(
        legacy.ComprehensiveDiscoverySpoolError,
        match="exceeded the existing evidence freshness epoch",
    ):
        coordinator._run_lane_transaction(
            tmp_path / "request.json",
            {"CAPITAL_INTELLIGENCE_RELEASE": "release-1"},
            asset_class="fx",
            index=0,
            decision_epoch=decision_epoch,
        )

    loaded = coordinator._run_lane_transaction(
        tmp_path / "request.json",
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-1"},
        asset_class="fx",
        index=0,
        decision_epoch=decision_epoch,
    )

    assert loaded is state
    assert len(spawned) == 2
