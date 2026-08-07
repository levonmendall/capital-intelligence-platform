from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations.composite_readiness import component_heartbeat_path
from operations.heartbeat import WorkerHeartbeatStore
from run_render_service_nonblocking import (
    _release_components_ready,
    _release_diagnostic_audit_command,
    _release_diagnostic_command,
    _release_diagnostic_environment,
    _start_release_diagnostic,
)


def test_release_diagnostic_command_honors_force_flag() -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_FORCE_ON_RELEASE": "true"
    }

    assert _release_diagnostic_command(
        values,
        python_executable="python-test",
    ) == ("python-test", "run_bounded_manual_cio_diagnostic.py", "--force")


def test_release_diagnostic_command_is_not_forced_by_default() -> None:
    assert _release_diagnostic_command(
        {},
        python_executable="python-test",
    ) == ("python-test", "run_bounded_manual_cio_diagnostic.py")


def test_release_diagnostic_retry_forces_a_replacement() -> None:
    assert _release_diagnostic_command(
        {},
        force=True,
        python_executable="python-test",
    ) == ("python-test", "run_bounded_manual_cio_diagnostic.py", "--force")


def test_release_diagnostic_audit_command_uses_static_publisher() -> None:
    assert _release_diagnostic_audit_command(
        python_executable="python-test"
    ) == ("python-test", "publish_cio_diagnostic_audit.py")


def test_release_diagnostic_requires_complete_live_all_market_scope() -> None:
    values = {
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE": "true",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "false",
        "CAPITAL_INTELLIGENCE_UNRELATED_SETTING": "preserved",
    }

    diagnostic = _release_diagnostic_environment(values)

    assert diagnostic["CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE"] == "false"
    assert diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] == "true"
    assert (
        diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY"]
        == "true"
    )
    assert (
        diagnostic["CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE"]
        == "true"
    )
    assert diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER"] == "true"
    assert diagnostic["CAPITAL_INTELLIGENCE_PROVIDER_RUNTIME_MODE"] == "live"
    assert (
        diagnostic[
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED"
        ]
        == "true"
    )
    assert diagnostic["CAPITAL_INTELLIGENCE_UNRELATED_SETTING"] == "preserved"
    assert values["CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE"] == "true"


def test_release_readiness_requires_current_healthy_api_and_streamlit(
    tmp_path: Path,
) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    not_before = datetime.now(timezone.utc)
    old = not_before - timedelta(minutes=5)

    for component in ("api", "streamlit"):
        WorkerHeartbeatStore(
            component_heartbeat_path(tmp_path, component)
        ).write("healthy", observed_at=old)

    assert not _release_components_ready(values, not_before=not_before)

    current = not_before + timedelta(seconds=1)
    for component in ("api", "streamlit"):
        WorkerHeartbeatStore(
            component_heartbeat_path(tmp_path, component)
        ).write("healthy", observed_at=current)

    assert _release_components_ready(values, not_before=not_before)


def test_release_diagnostic_is_not_armed_when_disabled() -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "false",
    }

    assert _start_release_diagnostic(values) is None
