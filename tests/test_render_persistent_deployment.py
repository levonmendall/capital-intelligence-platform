from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from portfolio.state import ensure_canonical_portfolio_store
from run_render_service import managed_processes, prepare_render_environment


BLUEPRINT = Path("render.yaml")


def test_render_blueprint_defines_one_paid_disk_backed_operating_service() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert source.count("  - type: web\n") == 1
    assert "runtime: docker" in source
    assert "plan: standard" in source
    assert "plan: starter" not in source
    assert "autoDeployTrigger: checksPass" in source
    assert "numInstances: 1" in source
    assert "dockerCommand: python run_render_service.py" in source
    assert "healthCheckPath: /_stcore/health" in source
    assert "mountPath: /app/database" in source
    assert "sizeGB: 5" in source
    assert "maxShutdownDelaySeconds" not in source
    assert "previews:\n  generation: off" in source


def test_render_blueprint_prompts_for_only_human_or_provider_secrets() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    for key in (
        "CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL",
        "CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "FRED_API_KEY",
    ):
        block = f"- key: {key}\n        sync: false"
        assert block in source
    assert "CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY" not in source
    assert "CAPITAL_INTELLIGENCE_METRICS_TOKEN" not in source


def test_render_environment_uses_persistent_state_and_internal_secrets(tmp_path) -> None:
    environment: dict[str, str] = {
        "RENDER": "true",
        "RENDER_GIT_COMMIT": "a" * 40,
        "RENDER_EXTERNAL_HOSTNAME": "capital-intelligence.onrender.com",
        "RENDER_EXTERNAL_URL": "https://capital-intelligence.onrender.com",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }

    prepared = prepare_render_environment(environment)

    assert prepared["CAPITAL_INTELLIGENCE_ENVIRONMENT"] == "production"
    assert prepared["CAPITAL_INTELLIGENCE_RELEASE"] == "a" * 40
    assert prepared["CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY"] == str(
        tmp_path / "backups"
    )
    assert prepared["CAPITAL_INTELLIGENCE_CIO_REPORT_DIRECTORY"] == str(
        tmp_path / "cio_reports"
    )
    assert prepared["CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR"] == str(
        tmp_path / "historical_replay"
    )
    assert prepared["CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG"] == (
        "config/historical_replay_free_sources.json"
    )
    assert prepared["CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS"] == "86400"
    assert prepared["CAPITAL_INTELLIGENCE_HISTORICAL_MAX_RECORDS_PER_SOURCE"] == "100000"
    assert (tmp_path / "historical_replay").is_dir()
    assert prepared["CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS"] == (
        "https://capital-intelligence.onrender.com"
    )
    allowed_hosts = set(prepared["CAPITAL_INTELLIGENCE_ALLOWED_HOSTS"].split(","))
    assert allowed_hosts == {
        "capital-intelligence.onrender.com",
        "localhost",
        "127.0.0.1",
    }
    assert len(prepared["CAPITAL_INTELLIGENCE_METRICS_TOKEN"]) >= 24
    Fernet(prepared["CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY"].encode("ascii"))
    assert (tmp_path / ".metrics-token").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".backup-encryption-key").stat().st_mode & 0o777 == 0o600

    second_environment = dict(environment)
    second_environment.pop("CAPITAL_INTELLIGENCE_METRICS_TOKEN", None)
    second_environment.pop("CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY", None)
    second = prepare_render_environment(second_environment)
    assert second["CAPITAL_INTELLIGENCE_METRICS_TOKEN"] == prepared[
        "CAPITAL_INTELLIGENCE_METRICS_TOKEN"
    ]
    assert second["CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY"] == prepared[
        "CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY"
    ]


def test_render_supervisor_starts_complete_operating_topology() -> None:
    processes = managed_processes(port=10000, python_executable="python")
    by_name = {process.name: process for process in processes}

    assert set(by_name) == {
        "api",
        "cio-paper-operator",
        "historical-backfill",
        "encrypted-backup",
        "streamlit",
    }
    assert by_name["api"].command == (
        "python",
        "-m",
        "uvicorn",
        "api.app:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--workers",
        "1",
        "--proxy-headers",
    )
    assert by_name["cio-paper-operator"].command == (
        "python",
        "run_autonomous_paper_operator.py",
        "--loop",
    )
    assert by_name["historical-backfill"].command == (
        "python",
        "run_historical_backfill.py",
        "--loop",
    )
    assert by_name["historical-backfill"].critical is False
    assert by_name["historical-backfill"].restart_delay_seconds == 300
    assert by_name["encrypted-backup"].command == (
        "python",
        "run_backup.py",
        "--loop",
    )
    assert by_name["encrypted-backup"].critical is False
    assert by_name["encrypted-backup"].restart_delay_seconds == 300
    assert "render_app.py" in by_name["streamlit"].command
    assert "--server.port=10000" in by_name["streamlit"].command
    assert all(
        process.critical
        for process in processes
        if process.name not in {"historical-backfill", "encrypted-backup"}
    )


def test_render_interface_displays_release_and_persistent_state_identity() -> None:
    from render_app import deployment_context_from_environment

    context = deployment_context_from_environment()
    assert context.release
    assert isinstance(context.state_root, Path)


def test_render_entrypoint_renders_complete_authenticated_console(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
        str(tmp_path / "canonical_portfolio.db"),
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_JOURNAL_DATABASE",
        str(tmp_path / "institutional_journal.db"),
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE",
        str(tmp_path / "full_universe_screening.db"),
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE",
        str(tmp_path / "daily_intelligence_snapshots.db"),
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_IDENTITY_DATABASE",
        str(tmp_path / "identity.db"),
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_ALERT_DATABASE",
        str(tmp_path / "alerts.db"),
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED", "false")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL", "false")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_REQUIRE_CANONICAL_ENVIRONMENT", "false")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE", "disabled")
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED",
        "false",
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT",
        "2999-01-01T00:00:00+00:00",
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE", "UTC")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "23")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS", "60")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_RELEASE", "render-smoke-test")
    monkeypatch.setenv(
        "RENDER_EXTERNAL_HOSTNAME",
        "capital-intelligence.onrender.com",
    )
    ensure_canonical_portfolio_store(tmp_path / "canonical_portfolio.db")

    app = AppTest.from_file("render_app.py", default_timeout=30).run()

    assert not app.exception
    assert len(app.segmented_control) == 1
    captions = [item.value for item in app.caption]
    assert "Public read-only viewer" in captions
    assert any("controls are private" in value for value in captions)
    assert any("Persistent operating host" in value for value in captions)
    assert any("render-smoke" in value for value in captions)
    assert any(str(tmp_path) in value for value in captions)
    assert "Sign out" not in [item.label for item in app.button]
    assert "Production smoke test" not in [item.label for item in app.button]
    for surface in ("Today", "Environment", "Portfolio", "History"):
        app.segmented_control[0].set_value(surface)
        app.run()
        assert not app.exception, surface
        assert app.segmented_control[0].value == surface


def test_render_supervisor_source_avoids_shell_execution_and_live_money() -> None:
    source = Path("run_render_service.py").read_text(encoding="utf-8")

    assert "shell=True" not in source
    assert "real_money_authorized" in source
    assert '"real_money_authorized": False' in source
    assert "subprocess.run(" in source
    assert '"initialize.py"' in source
