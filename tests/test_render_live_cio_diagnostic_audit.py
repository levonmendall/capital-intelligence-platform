import subprocess

import run_render_service_nonblocking as bootstrap


def test_release_diagnostic_republishes_public_audit_while_running(monkeypatch):
    command = ("python", "run_bounded_manual_cio_diagnostic.py")
    diagnostic_values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-live-static-audit",
        "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/capital-intelligence-test",
    }
    observed: dict[str, object] = {}
    waits: list[float | None] = []
    publications: list[dict[str, str]] = []

    class FakeProcess:
        def wait(self, timeout=None):
            waits.append(timeout)
            if len(waits) == 1:
                raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)
            return 0

    def fake_popen(received_command, *, env):
        observed["command"] = tuple(received_command)
        observed["env"] = dict(env)
        return FakeProcess()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        bootstrap,
        "_publish_release_diagnostic_audit",
        lambda values: publications.append(dict(values)) or 0,
    )

    return_code = bootstrap._run_release_diagnostic_with_live_audit(
        command,
        diagnostic_values=diagnostic_values,
        refresh_seconds=0.01,
    )

    assert return_code == 0
    assert observed["command"] == command
    assert observed["env"] == diagnostic_values
    assert waits == [0.01, 0.01]
    assert publications == [diagnostic_values]


def test_release_diagnostic_does_not_publish_extra_snapshot_when_it_finishes_immediately(
    monkeypatch,
):
    publications: list[dict[str, str]] = []

    class FakeProcess:
        def wait(self, timeout=None):
            assert timeout == 0.01
            return 6

    monkeypatch.setattr(
        bootstrap.subprocess,
        "Popen",
        lambda _command, *, env: FakeProcess(),
    )
    monkeypatch.setattr(
        bootstrap,
        "_publish_release_diagnostic_audit",
        lambda values: publications.append(dict(values)) or 0,
    )

    return_code = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values={"CAPITAL_INTELLIGENCE_RELEASE": "release-terminal"},
        refresh_seconds=0.01,
    )

    assert return_code == 6
    assert publications == []
