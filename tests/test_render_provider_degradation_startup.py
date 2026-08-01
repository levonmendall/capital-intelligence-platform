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

    # Startup still performs and persists credential-safe provider validation.
    assert (
        _environment_value(
            source,
            "CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP",
        )
        == "true"
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
