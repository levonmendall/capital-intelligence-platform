from pathlib import Path


BLUEPRINT = Path("render.yaml")


def test_render_runs_daily_cio_after_market_open_quotes() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert source.count("- key: CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE\n") == 1
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE\n"
        "        value: America/Los_Angeles"
    ) in source
    assert source.count("- key: CAPITAL_INTELLIGENCE_SCHEDULER_HOUR\n") == 1
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_HOUR\n"
        "        value: \"7\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS\n"
        "        value: \"60\""
    ) in source


def test_render_refreshes_public_information_before_morning_cycle() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    assert (
        "- key: CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED\n"
        "        value: \"true\""
    ) in source
    assert (
        "- key: CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS\n"
        "        value: \"1800\""
    ) in source
    assert "autoDeployTrigger: checksPass" in source
    assert "dockerCommand: python run_render_service.py" in source


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
