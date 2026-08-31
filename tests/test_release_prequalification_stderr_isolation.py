from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from operations import release_prequalification_stderr_isolation as isolation


def test_qualifier_stderr_is_disk_backed_and_bounded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(isolation, "_release_retry_heap", lambda: None)
    safe_failure = json.dumps(
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
        }
    )
    payload = ("discard-me\n" * (isolation._TAIL_BYTES // 5) + safe_failure + "\n").encode()
    observed = {}

    def fake_run(*args, **kwargs):
        observed["stderr"] = kwargs.get("stderr")
        assert kwargs.get("stderr") is not subprocess.PIPE
        kwargs["stderr"].write(payload)
        return subprocess.CompletedProcess(args[0], 125, stdout=None, stderr=None)

    delegate = SimpleNamespace(
        PIPE=subprocess.PIPE,
        CompletedProcess=subprocess.CompletedProcess,
        run=fake_run,
    )
    proxy = isolation._SubprocessProxy(delegate)
    completed = proxy.run(
        ("python", "run_bounded_continuous_evidence_plane.py", "--once"),
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert observed["stderr"] is not subprocess.PIPE
    assert safe_failure in completed.stderr
    assert len(completed.stderr.encode("utf-8")) <= isolation._TAIL_BYTES


def test_nonqualifier_subprocess_preserves_original_pipe(monkeypatch) -> None:
    monkeypatch.setattr(isolation, "_release_retry_heap", lambda: None)
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs.get("stderr"))
        return subprocess.CompletedProcess(args[0], 0, stdout=None, stderr="original")

    delegate = SimpleNamespace(
        PIPE=subprocess.PIPE,
        CompletedProcess=subprocess.CompletedProcess,
        run=fake_run,
    )
    proxy = isolation._SubprocessProxy(delegate)
    completed = proxy.run(
        ("python", "unrelated_worker.py"),
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert seen == [subprocess.PIPE]
    assert completed.stderr == "original"


def test_install_is_module_local_and_idempotent() -> None:
    real_run = subprocess.run
    memory_safe = SimpleNamespace(subprocess=subprocess)

    isolation.install(memory_safe)
    first = memory_safe.subprocess
    isolation.install(memory_safe)

    assert isinstance(first, isolation._SubprocessProxy)
    assert memory_safe.subprocess is first
    assert subprocess.run is real_run
