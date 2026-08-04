"""Tests for Render startup that does not wait on external providers."""

from __future__ import annotations

from pathlib import Path

import run_render_service_nonblocking as bootstrap


class FakeProcess:
    pid = 4321

    def __init__(self) -> None:
        self.terminated = False
        self.waited = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        self.waited = True
        return 0

    def kill(self) -> None:
        self.terminated = True


def test_background_validation_is_detached_before_supervisor(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP": "true",
    }
    process = FakeProcess()
    popen_calls = []
    supervisor_calls = []

    monkeypatch.setattr(bootstrap, "prepare_render_environment", lambda env: env)

    def popen(command, *, env):
        popen_calls.append((command, env))
        return process

    monkeypatch.setattr(bootstrap.subprocess, "Popen", popen)

    def run_supervisor(*, environment):
        supervisor_calls.append(environment)
        return 0

    monkeypatch.setattr(bootstrap, "run_supervisor", run_supervisor)

    assert bootstrap.run_nonblocking_render_service(values) == 0
    assert values["CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP"] == "false"
    assert popen_calls[0][0][1:] == (
        "run_background_provider_validation.py",
        "--loop",
    )
    assert supervisor_calls == [values]
    assert process.terminated is True
    assert process.waited is True


def test_disabled_background_validation_preserves_existing_startup_mode(
    monkeypatch,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "false",
        "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP": "true",
    }
    monkeypatch.setattr(bootstrap, "prepare_render_environment", lambda env: env)

    def unexpected_popen(*args, **kwargs):
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(bootstrap.subprocess, "Popen", unexpected_popen)
    monkeypatch.setattr(
        bootstrap,
        "run_supervisor",
        lambda *, environment: 0 if environment is values else 1,
    )

    assert bootstrap.run_nonblocking_render_service(values) == 0
    assert values["CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP"] == "true"


def test_render_blueprint_uses_nonblocking_bootstrap() -> None:
    text = Path("render.yaml").read_text(encoding="utf-8")

    assert "dockerCommand: python run_render_service_nonblocking.py" in text
    assert "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP\n        value: \"false\"" in text
    assert "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED" in text
    assert "CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER\n        value: \"true\"" in text
    assert "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY\n        value: \"true\"" in text
