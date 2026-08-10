from __future__ import annotations

import inspect
from pathlib import Path

import run_bounded_render_worker as bounded_worker
import run_locked_background_provider_validation as locked_provider
import run_render_service_memory_safe as memory_safe_service
from render_memory_lane import acquire_memory_lane


def test_memory_safe_supervisor_replaces_resident_heavy_loops() -> None:
    specs = {
        spec.name: spec
        for spec in memory_safe_service.memory_safe_managed_processes(
            port=10000,
            python_executable="python-test",
        )
    }

    operator = specs["cio-paper-operator"].command
    historical = specs["historical-backfill"].command
    backup = specs["encrypted-backup"].command

    assert operator[:4] == (
        "python-test",
        "run_bounded_render_worker.py",
        "cio-paper-operator",
        "--loop",
    )
    assert "run_autonomous_paper_operator.py" not in operator
    assert historical[:4] == (
        "python-test",
        "run_bounded_render_worker.py",
        "historical-backfill",
        "--loop",
    )
    assert backup[:4] == (
        "python-test",
        "run_bounded_render_worker.py",
        "encrypted-backup",
        "--loop",
    )
    assert historical[-1] == "1800"
    assert backup[-1] == "900"


def test_cio_operator_pass_is_short_lived_and_bounded() -> None:
    operator = bounded_worker._WORKERS["cio-paper-operator"]
    assert operator.script == "run_autonomous_paper_operator.py"
    assert operator.arguments == ("--once",)

    source = inspect.getsource(bounded_worker._run_isolated_once)
    assert "acquire_memory_lane" in source
    assert "_wait_with_resource_bounds" in source
    assert 'start_new_session=(os.name == "posix")' in source
    assert "service_oom_prevented=True" in source


def test_historical_and_backup_work_no_longer_retain_heavy_loop_imports() -> None:
    historical = bounded_worker._WORKERS["historical-backfill"]
    backup = bounded_worker._WORKERS["encrypted-backup"]
    assert historical.arguments == ()
    assert backup.arguments == ()
    assert historical.default_initial_delay_seconds == 1800.0
    assert backup.default_initial_delay_seconds == 900.0


def test_provider_validation_joins_same_heavy_memory_lane() -> None:
    source = inspect.getsource(locked_provider._run_locked_validation)
    assert 'acquire_memory_lane(' in source
    assert '"provider-validation"' in source
    assert "_ORIGINAL_ISOLATED_VALIDATION" in source
    assert "lease.release()" in source


def test_memory_lane_serializes_cross_process_heavy_work(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RENDER_MEMORY_LANE_LOCK": str(tmp_path / "lane.lock"),
    }
    first = acquire_memory_lane(
        "first",
        values=values,
        timeout_seconds=0.0,
        poll_seconds=0.01,
    )
    assert first is not None
    try:
        second = acquire_memory_lane(
            "second",
            values=values,
            timeout_seconds=0.0,
            poll_seconds=0.01,
        )
        assert second is None
    finally:
        first.release()

    third = acquire_memory_lane(
        "third",
        values=values,
        timeout_seconds=0.0,
        poll_seconds=0.01,
    )
    assert third is not None
    third.release()


def test_render_workspace_routes_production_through_memory_safe_bootstrap() -> None:
    source = Path("run_render_service_workspace.py").read_text(encoding="utf-8")
    assert "from run_render_service_memory_safe import main as run_service" in source
    assert "from run_render_service_nonblocking import main as run_service" not in source
