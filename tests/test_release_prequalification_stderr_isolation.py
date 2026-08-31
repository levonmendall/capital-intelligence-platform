from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

from operations import release_prequalification_parent_watchdog as parent
from operations import release_prequalification_stderr_isolation as isolation
from operations import release_prequalification_timeout_contract as timeout_contract


def _safe_failure() -> str:
    return json.dumps(
        {
            "event": "continuous_evidence_plane_failure_context",
            "error_type": "ResourceBoundaryExceeded",
            "failure_stage": "stage_isolated_evidence:us_equity_discovery",
            "error_detail": "bounded failure",
            "credential_safe": True,
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
        sort_keys=True,
    )


def test_bounded_tail_retains_terminal_failure_without_full_log(tmp_path) -> None:
    safe_failure = _safe_failure()
    payload = (b"discard-me\n" * (isolation._TAIL_BYTES // 4)) + safe_failure.encode() + b"\n"

    with tempfile.TemporaryFile(mode="w+b", dir=tmp_path) as handle:
        handle.write(payload)
        captured = isolation._bounded_tail(handle, text_mode=True)

    assert isinstance(captured, str)
    assert safe_failure in captured
    assert len(captured.encode("utf-8")) <= isolation._TAIL_BYTES


def test_post_882_isolation_preserves_parent_watchdog_bootstrap_contract(monkeypatch) -> None:
    original_watched_run = parent._watched_run
    monkeypatch.delattr(parent, isolation._INSTALLED_ATTR, raising=False)
    monkeypatch.setattr(parent, "_watched_run", original_watched_run)

    memory_safe = SimpleNamespace(subprocess=subprocess)

    isolation.install(memory_safe)

    # The production regression was caused by replacing this module object before the
    # parent watchdog installed. The isolation hook must now leave it canonical.
    assert memory_safe.subprocess is subprocess
    assert parent._watched_run is isolation._bounded_parent_watched_run

    parent.install_release_prequalification_parent_watchdog(memory_safe)

    assert isinstance(memory_safe.subprocess, parent._SubprocessProxy)


def test_full_render_watchdog_install_chain_remains_composable(monkeypatch) -> None:
    original_watched_run = parent._watched_run
    monkeypatch.delattr(parent, isolation._INSTALLED_ATTR, raising=False)
    monkeypatch.setattr(parent, "_watched_run", original_watched_run)
    monkeypatch.setattr(timeout_contract, "_install_parent_progress_adapters", lambda: None)
    memory_safe = SimpleNamespace(subprocess=subprocess)

    isolation.install(memory_safe)
    parent.install_release_prequalification_parent_watchdog(memory_safe)
    timeout_contract.install_release_prequalification_timeout_contract(memory_safe)

    assert isinstance(
        memory_safe.subprocess,
        timeout_contract._ProgressSupervisedSubprocessProxy,
    )
    assert isinstance(memory_safe.subprocess._parent_proxy, parent._SubprocessProxy)
    assert parent._watched_run is isolation._bounded_parent_watched_run


def test_isolation_install_is_idempotent_and_module_local(monkeypatch) -> None:
    original_watched_run = parent._watched_run
    monkeypatch.delattr(parent, isolation._INSTALLED_ATTR, raising=False)
    monkeypatch.setattr(parent, "_watched_run", original_watched_run)
    memory_safe = SimpleNamespace(subprocess=subprocess)

    isolation.install(memory_safe)
    first = parent._watched_run
    isolation.install(memory_safe)

    assert first is isolation._bounded_parent_watched_run
    assert parent._watched_run is first
    assert memory_safe.subprocess is subprocess
    assert subprocess.run is not isolation._bounded_parent_watched_run


def test_parent_watched_run_returns_only_bounded_disk_backed_stderr(monkeypatch, tmp_path) -> None:
    safe_failure = _safe_failure()
    payload = (b"discard-me\n" * (isolation._TAIL_BYTES // 4)) + safe_failure.encode() + b"\n"
    started = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    observed: dict[str, object] = {}

    monkeypatch.setattr(isolation, "_release_retry_heap", lambda: None)
    monkeypatch.setattr(
        parent,
        "load_release_evidence_prequalification",
        lambda values: {"started_at": started.isoformat()},
    )
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    class FakeProcess:
        returncode = 125
        pid = 12345

        def __init__(self, command, *, stderr, **kwargs):
            observed["command"] = command
            observed["stderr"] = stderr
            observed["kwargs"] = kwargs
            stderr.write(payload)
            stderr.flush()

        def poll(self):
            return self.returncode

    monkeypatch.setattr(parent._subprocess, "Popen", FakeProcess)

    completed = isolation._bounded_parent_watched_run(
        ("python", "run_bounded_continuous_evidence_plane.py", "--once"),
        original_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("qualifier should use watched path")
        ),
        env={"TMPDIR": str(tmp_path)},
        stderr=parent._subprocess.PIPE,
        text=True,
        check=False,
    )

    assert observed["stderr"] is not parent._subprocess.PIPE
    assert completed.returncode == 125
    assert isinstance(completed.stderr, str)
    assert safe_failure in completed.stderr
    assert len(completed.stderr.encode("utf-8")) <= isolation._TAIL_BYTES


def test_parent_watched_run_preserves_check_semantics(monkeypatch, tmp_path) -> None:
    started = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(isolation, "_release_retry_heap", lambda: None)
    monkeypatch.setattr(
        parent,
        "load_release_evidence_prequalification",
        lambda values: {"started_at": started.isoformat()},
    )
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    class FakeProcess:
        returncode = 2
        pid = 12345

        def __init__(self, command, *, stderr, **kwargs):
            stderr.write(b"failed\n")
            stderr.flush()

        def poll(self):
            return self.returncode

    monkeypatch.setattr(parent._subprocess, "Popen", FakeProcess)

    try:
        isolation._bounded_parent_watched_run(
            ("python", "run_bounded_continuous_evidence_plane.py", "--once"),
            original_run=subprocess.run,
            env={"TMPDIR": str(tmp_path)},
            stderr=parent._subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        assert error.returncode == 2
        assert error.stderr == "failed\n"
    else:
        raise AssertionError("check=True must preserve CalledProcessError semantics")
