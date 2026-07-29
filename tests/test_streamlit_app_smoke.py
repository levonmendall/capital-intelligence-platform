from __future__ import annotations

from streamlit.testing.v1 import AppTest

from portfolio.state import ensure_canonical_portfolio_store


def test_all_four_streamlit_screens_render_in_clean_runtime(monkeypatch, tmp_path) -> None:
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
    # This smoke test validates deterministic rendering rather than external network
    # availability. Dedicated runtime-collector tests cover the enabled collection path.
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
    ensure_canonical_portfolio_store(tmp_path / "canonical_portfolio.db")

    app = AppTest.from_file("app.py", default_timeout=30).run()

    assert not app.exception
    assert len(app.segmented_control) == 1
    for surface in ("Today", "Environment", "Portfolio", "History"):
        app.segmented_control[0].set_value(surface)
        app.run()
        assert not app.exception, surface
        assert app.segmented_control[0].value == surface
