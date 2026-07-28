"""Contract tests for the distinct four-surface presentation system."""

from __future__ import annotations

import pytest

from premium_ui import SURFACE_PROFILES, _hero_visual, surface_profile


def test_primary_surfaces_have_distinct_visual_and_narrative_profiles() -> None:
    profiles = tuple(SURFACE_PROFILES.values())

    assert tuple(SURFACE_PROFILES) == (
        "Today",
        "Environment",
        "Portfolio",
        "History",
    )
    assert len({profile.title for profile in profiles}) == 4
    assert len({profile.kicker for profile in profiles}) == 4
    assert len({profile.core_label for profile in profiles}) == 4
    assert len({profile.accent for profile in profiles}) == 4
    assert len({profile.node_label for profile in profiles}) == 4


def test_each_surface_uses_a_different_hero_visual_language() -> None:
    markup = {
        name: _hero_visual(profile)
        for name, profile in SURFACE_PROFILES.items()
    }

    assert "visual-today" in markup["Today"]
    assert "visual-environment" in markup["Environment"]
    assert "visual-portfolio" in markup["Portfolio"]
    assert "visual-history" in markup["History"]
    assert len(set(markup.values())) == 4


def test_unknown_surface_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown application surface"):
        surface_profile("Research")
