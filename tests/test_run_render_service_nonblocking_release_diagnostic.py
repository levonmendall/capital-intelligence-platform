from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import run_render_service_nonblocking as bootstrap


def test_release_diagnostic_runs_after_bounded_readiness_wait_expires(monkeypatch):
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/capital-intelligence-test",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-under-test",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_STARTUP_WAIT_SECONDS": "0.5",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_STARTUP_POLL_SECONDS": "0.1",
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_MAX_ATTEMPTS": "1",
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_RETRY_SECONDS": "1",
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE": "true",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "false",
    }
    published: list[dict[str, str]] = []
    executed: list[tuple[tuple[str, ...], dict[str, str]]] = []
    logged: list[tuple[str, dict[str, object]]] = []
    monotonic_values = iter((0.0, 1.0))

    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        bootstrap,
        "_publish_release_diagnostic_audit",
        lambda environment: published.append(dict(environment)) or 0,
    )
    monkeypatch.setattr(
        bootstrap,
        "_log",
        lambda event, **details: logged.append((event, details)),
    )

    def fake_run(command, *, env, check):
        assert check is False
        executed.append((tuple(command), dict(env)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    bootstrap._run_release_diagnostic_after_readiness(
        values,
        not_before=datetime.now(timezone.utc),
    )

    assert len(executed) == 1
    command, diagnostic_environment = executed[0]
    assert command[-1] == "run_manual_cio_diagnostic.py"
    assert diagnostic_environment["CAPITAL_INTELLIGENCE_RELEASE"] == "release-under-test"
    assert diagnostic_environment["CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE"] == "false"
    assert diagnostic_environment["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] == "true"
    assert diagnostic_environment["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY"] == "true"
    assert diagnostic_environment["CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE"] == "true"
    assert diagnostic_environment["CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER"] == "true"
    assert len(published) == 2
    assert any(
        event == "manual_cio_release_diagnostic_readiness_wait_expired"
        and details["complete_all_market_coverage_required"] is True
        and details["paper_only"] is True
        for event, details in logged
    )
    assert not any(event == "manual_cio_release_diagnostic_not_started" for event, _ in logged)
