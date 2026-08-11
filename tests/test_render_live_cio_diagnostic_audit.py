from types import SimpleNamespace

import run_render_service_nonblocking as bootstrap


def test_live_audit_publisher_republishes_until_stopped(monkeypatch):
    diagnostic_values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-live-static-audit",
        "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/capital-intelligence-test",
    }
    waits: list[float] = []
    publications: list[dict[str, str]] = []

    class FakeStopEvent:
        def wait(self, timeout):
            waits.append(timeout)
            return len(waits) > 1

    monkeypatch.setattr(
        bootstrap,
        "_publish_release_diagnostic_audit",
        lambda values: publications.append(dict(values)) or 0,
    )

    bootstrap._refresh_release_diagnostic_audit_until_stopped(
        FakeStopEvent(),
        diagnostic_values=diagnostic_values,
        refresh_seconds=15.0,
    )

    assert waits == [15.0, 15.0]
    assert publications == [diagnostic_values]


def test_release_diagnostic_preserves_subprocess_run_contract(monkeypatch):
    command = ("python", "run_bounded_manual_cio_diagnostic.py")
    diagnostic_values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-run-contract",
    }
    observed: dict[str, object] = {}
    publications: list[dict[str, str]] = []

    def fake_run(received_command, *, env, check):
        observed["command"] = tuple(received_command)
        observed["env"] = dict(env)
        observed["check"] = check
        return SimpleNamespace(returncode=6)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setattr(
        bootstrap,
        "_publish_release_diagnostic_audit",
        lambda values: publications.append(dict(values)) or 0,
    )

    return_code = bootstrap._run_release_diagnostic_with_live_audit(
        command,
        diagnostic_values=diagnostic_values,
        refresh_seconds=15.0,
    )

    assert return_code == 6
    assert observed == {
        "command": command,
        "env": diagnostic_values,
        "check": False,
    }
    assert publications == []
