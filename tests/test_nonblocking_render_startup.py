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


class FakeStorageReport:
    def to_dict(self):
        return {
            "recovered": False,
            "reserve_satisfied": True,
            "canonical_authorities_deleted": False,
        }


def _safe_storage(monkeypatch) -> None:
    monkeypatch.setattr(
        bootstrap,
        "reclaim_from_environment",
        lambda _values: FakeStorageReport(),
    )


def test_background_validation_is_detached_before_supervisor(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP": "true",
    }
    process = FakeProcess()
    popen_calls = []
    supervisor_calls = []

    monkeypatch.setattr(bootstrap, "prepare_render_environment", lambda env: env)
    _safe_storage(monkeypatch)

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
    _safe_storage(monkeypatch)

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


def test_storage_recovery_runs_before_supervisor(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "false",
    }
    events = []

    def prepare(environment):
        events.append("prepare")
        return environment

    def reclaim(environment):
        assert environment is values
        events.append("reclaim")
        return FakeStorageReport()

    def supervisor(*, environment):
        assert environment is values
        events.append("supervisor")
        return 0

    monkeypatch.setattr(bootstrap, "prepare_render_environment", prepare)
    monkeypatch.setattr(bootstrap, "reclaim_from_environment", reclaim)
    monkeypatch.setattr(bootstrap, "run_supervisor", supervisor)

    assert bootstrap.run_nonblocking_render_service(values) == 0
    assert events == ["prepare", "reclaim", "supervisor"]


def test_bond_source_transition_makes_only_the_expansion_optional(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "false",
        "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP": "false",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE": "true",
    }
    supervisor_calls = []
    monkeypatch.setattr(bootstrap, "prepare_render_environment", lambda env: env)
    _safe_storage(monkeypatch)
    monkeypatch.setattr(
        bootstrap,
        "run_supervisor",
        lambda *, environment: supervisor_calls.append(environment) or 0,
    )

    assert bootstrap.run_nonblocking_render_service(values) == 0
    assert supervisor_calls == [values]
    assert values["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] == "false"


def test_transition_mode_is_explicit_and_disabled_by_default(monkeypatch) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "false",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
    }
    monkeypatch.setattr(bootstrap, "prepare_render_environment", lambda env: env)
    _safe_storage(monkeypatch)
    monkeypatch.setattr(bootstrap, "run_supervisor", lambda *, environment: 0)

    assert bootstrap.run_nonblocking_render_service(values) == 0
    assert values["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] == "true"


def test_render_blueprint_uses_nonblocking_bootstrap() -> None:
    text = Path("render.yaml").read_text(encoding="utf-8")

    assert "dockerCommand: python run_render_service_nonblocking.py" in text
    assert "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP\n        value: \"false\"" in text
    assert "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED" in text
    assert "CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER\n        value: \"true\"" in text
    assert "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY\n        value: \"true\"" in text
    assert "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE\n        value: \"true\"" in text
    assert "CAPITAL_INTELLIGENCE_BACKUP_RETENTION_DAYS\n        value: \"1\"" in text
    assert "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB\n        value: \"1024\"" in text
    assert "CAPITAL_INTELLIGENCE_BACKUP_MINIMUM_ARCHIVES\n        value: \"1\"" in text
