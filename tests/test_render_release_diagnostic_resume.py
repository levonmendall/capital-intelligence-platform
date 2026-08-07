from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import run_render_service_nonblocking as bootstrap


NOW = datetime(2026, 8, 5, 22, 0, tzinfo=timezone.utc)


def _values(
    tmp_path,
    *,
    max_attempts: int,
    retry_seconds: float = 0.25,
) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "test-release-sha",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_STARTUP_WAIT_SECONDS": "1",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_STARTUP_POLL_SECONDS": "0.1",
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_MAX_ATTEMPTS": str(max_attempts),
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_RETRY_SECONDS": str(
            retry_seconds
        ),
    }


def _install_ready_audit_fakes(monkeypatch, audit_calls: list[str]) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_release_components_ready",
        lambda _values, *, not_before: not_before == NOW,
    )
    monkeypatch.setattr(
        bootstrap,
        "_publish_release_diagnostic_audit",
        lambda values: audit_calls.append(values["CAPITAL_INTELLIGENCE_RELEASE"])
        or 0,
    )


def test_failed_cold_start_resumes_from_cache_and_stops_on_success(
    tmp_path,
    monkeypatch,
) -> None:
    audit_calls: list[str] = []
    sleeps: list[float] = []
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []
    return_codes = iter((1, 0))
    _install_ready_audit_fakes(monkeypatch, audit_calls)
    monkeypatch.setattr(bootstrap.time, "sleep", sleeps.append)

    def run(command, *, env, check):
        assert check is False
        commands.append(tuple(command))
        environments.append(dict(env))
        return SimpleNamespace(returncode=next(return_codes))

    monkeypatch.setattr(bootstrap.subprocess, "run", run)

    bootstrap._run_release_diagnostic_after_readiness(
        _values(tmp_path, max_attempts=4),
        not_before=NOW,
    )

    assert len(commands) == 2
    assert commands[0][-1] == "run_bounded_manual_cio_diagnostic.py"
    assert commands[1][-2:] == (
        "run_bounded_manual_cio_diagnostic.py",
        "--force",
    )
    assert sleeps == [0.25]
    assert audit_calls == ["test-release-sha"] * 3
    assert all(
        values["CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE"]
        == "true"
        for values in environments
    )
    assert all(
        values["CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE"] == "false"
        for values in environments
    )


def test_repeated_failures_stop_at_the_configured_bound(
    tmp_path,
    monkeypatch,
) -> None:
    audit_calls: list[str] = []
    sleeps: list[float] = []
    commands: list[tuple[str, ...]] = []
    _install_ready_audit_fakes(monkeypatch, audit_calls)
    monkeypatch.setattr(bootstrap.time, "sleep", sleeps.append)

    def run(command, *, env: dict[str, str], check: bool):
        assert env["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] == "true"
        assert check is False
        commands.append(tuple(command))
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)

    bootstrap._run_release_diagnostic_after_readiness(
        _values(tmp_path, max_attempts=3, retry_seconds=0.5),
        not_before=NOW,
    )

    assert len(commands) == 3
    assert sleeps == [0.5, 0.5]
    assert audit_calls == ["test-release-sha"] * 4


def test_single_attempt_preserves_one_shot_behavior(
    tmp_path,
    monkeypatch,
) -> None:
    audit_calls: list[str] = []
    sleeps: list[float] = []
    commands: list[tuple[str, ...]] = []
    _install_ready_audit_fakes(monkeypatch, audit_calls)
    monkeypatch.setattr(bootstrap.time, "sleep", sleeps.append)

    def run(command, **_kwargs: Any):
        commands.append(tuple(command))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)

    bootstrap._run_release_diagnostic_after_readiness(
        _values(tmp_path, max_attempts=1),
        not_before=NOW,
    )

    assert len(commands) == 1
    assert sleeps == []
    assert audit_calls == ["test-release-sha", "test-release-sha"]


def test_retry_policy_rejects_unbounded_configuration(tmp_path) -> None:
    too_many = _values(tmp_path, max_attempts=13)
    with pytest.raises(ValueError, match="must be at most 12"):
        bootstrap._release_diagnostic_retry_policy(too_many)

    too_long = _values(tmp_path, max_attempts=2, retry_seconds=601.0)
    with pytest.raises(ValueError, match="must be at most 600"):
        bootstrap._release_diagnostic_retry_policy(too_long)
