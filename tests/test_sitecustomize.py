from __future__ import annotations

from sitecustomize import configure_code_version


def test_render_commit_populates_canonical_code_version() -> None:
    environment = {"RENDER_GIT_COMMIT": "render-release-abc"}

    resolved = configure_code_version(environment)

    assert resolved == "render-release-abc"
    assert environment["CAPITAL_INTELLIGENCE_CODE_VERSION"] == "render-release-abc"


def test_explicit_canonical_code_version_is_not_overridden() -> None:
    environment = {
        "CAPITAL_INTELLIGENCE_CODE_VERSION": "governed-release",
        "RENDER_GIT_COMMIT": "render-release-abc",
    }

    resolved = configure_code_version(environment)

    assert resolved == "governed-release"
    assert environment["CAPITAL_INTELLIGENCE_CODE_VERSION"] == "governed-release"


def test_missing_release_metadata_remains_unset() -> None:
    environment: dict[str, str] = {}

    assert configure_code_version(environment) is None
    assert "CAPITAL_INTELLIGENCE_CODE_VERSION" not in environment
