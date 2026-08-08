from pathlib import Path


BLUEPRINT = Path("render.yaml")


def test_render_runs_three_intraday_cio_reviews() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert source.count("- key: CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE\n") == 1
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE\n"
        "        value: America/Los_Angeles"
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_TIMES\n"
        "        value: 07:00,10:00,12:45"
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS\n"
        "        value: \"60\""
    ) in source


def test_render_scans_material_market_changes_every_five_minutes() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_SCAN_SECONDS\n"
        "        value: \"300\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_EVENT_COOLDOWN_MINUTES\n"
        "        value: \"30\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_BENCHMARK_MOVE_THRESHOLD\n"
        "        value: \"0.01\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_INSTRUMENT_MOVE_THRESHOLD\n"
        "        value: \"0.03\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_COMPANY_MOVE_THRESHOLD\n"
        "        value: \"0.05\""
    ) in source


def test_render_configures_research_only_after_close_review() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_AFTER_CLOSE_TIME\n"
        "        value: \"13:15\""
    ) in source


def test_render_refreshes_public_information_before_cio_reviews() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert (
        "- key: CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED\n"
        "        value: \"true\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS\n"
        "        value: \"900\""
    ) in source
    assert "autoDeployTrigger: checksPass" in source
    assert "dockerCommand: python run_render_service_workspace.py" in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP\n"
        "        value: \"false\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED\n"
        "        value: \"true\""
    ) in source


def test_render_requires_live_provider_and_canonical_environment() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert (
        "- key: CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER\n"
        "        value: \"true\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_REQUIRE_CANONICAL_ENVIRONMENT\n"
        "        value: \"true\""
    ) in source
    for key in (
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "FRED_API_KEY",
    ):
        assert f"- key: {key}\n        sync: false" in source
