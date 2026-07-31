"""Behavioral contracts for the canonical Streamlit composition."""

from __future__ import annotations

from app_impl import PRIMARY_SURFACES, _latest
from premium_ui import SURFACE_PROFILES, compact_header_markup, surface_profile
import app_impl


def test_signature_interface_keeps_four_simple_surfaces() -> None:
    assert PRIMARY_SURFACES == ["Today", "Environment", "Portfolio", "History"]
    assert tuple(SURFACE_PROFILES) == tuple(PRIMARY_SURFACES)
    assert {surface_profile(name).slug for name in PRIMARY_SURFACES} == {
        "today",
        "environment",
        "portfolio",
        "history",
    }


def test_each_surface_has_renderable_compact_identity() -> None:
    for name in PRIMARY_SURFACES:
        markup = compact_header_markup(surface_profile(name), "test UTC")
        assert markup.startswith('<div class="surface-marker')
        assert name in markup
        assert "test UTC" in markup


def test_optional_dashboard_reads_fail_soft(monkeypatch) -> None:
    class FailingJournal:
        def latest_payload(self, _event_type):
            raise RuntimeError("journal unavailable")

    monkeypatch.setattr(app_impl, "cio_journal", lambda: FailingJournal())
    assert _latest("daily_cio_briefing") is None


def test_streamlit_theme_defaults_to_signature_dark_mode() -> None:
    from pathlib import Path

    theme = (Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml").read_text(
        encoding="utf-8"
    )
    assert 'base = "dark"' in theme
    assert 'primaryColor = "#56E0FF"' in theme
