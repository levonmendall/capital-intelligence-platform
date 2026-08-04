from __future__ import annotations

from pathlib import Path


BLUEPRINT = Path("render.yaml")


def _environment_value(source: str, key: str) -> str:
    lines = source.splitlines()
    marker = f"- key: {key}"
    for index, line in enumerate(lines):
        if line.strip() != marker:
            continue
        for candidate in lines[index + 1 : index + 4]:
            stripped = candidate.strip()
            if stripped.startswith("value:"):
                return stripped.split(":", 1)[1].strip().strip('"')
        raise AssertionError(f"Render environment value is missing for {key}")
    raise AssertionError(f"Render environment key is missing: {key}")


def test_provider_degradation_keeps_render_console_online_and_cio_fail_closed() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")

    # External provider calls do not block Streamlit/API health during startup.
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP",
        )
        == "false"
    )

    # A noncritical worker still performs and persists credential-safe validation.
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED",
        )
        == "true"
    )
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_INITIAL_DELAY_SECONDS",
        )
        == "5"
    )
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_INTERVAL_SECONDS",
        )
        == "3600"
    )

    # A failed provider probe must not terminate Streamlit/API availability.
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_REQUIRED",
        )
        == "false"
    )

    # Provider-dependent CIO analysis and paper implementation remain fail-closed.
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER",
        )
        == "true"
    )
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_REQUIRE_CANONICAL_ENVIRONMENT",
        )
        == "true"
    )
    assert (
        _environment_value(source, "CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL")
        == "true"
    )
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY",
        )
        == "true"
    )
