from __future__ import annotations

import logging

import app_impl
import render_app


def test_render_entrypoint_replaces_all_primary_fragments_with_sync_guards() -> None:
    originals = {
        name: getattr(app_impl, name)
        for name in render_app._RENDER_SURFACE_NAMES
    }
    try:
        for renderer in originals.values():
            assert render_app._synchronous_renderer(renderer) is not renderer

        render_app.prepare_render_surface_runtime()

        for name in render_app._RENDER_SURFACE_NAMES:
            renderer = getattr(app_impl, name)
            assert renderer._capital_intelligence_guarded_surface is True
            assert renderer._capital_intelligence_fragment_removed is True
    finally:
        for name, renderer in originals.items():
            setattr(app_impl, name, renderer)


def test_surface_failure_is_logged_and_shown_instead_of_silent_blank(
    monkeypatch,
    caplog,
) -> None:
    visible_errors: list[str] = []
    visible_captions: list[str] = []
    monkeypatch.setattr(render_app.st, "error", visible_errors.append)
    monkeypatch.setattr(render_app.st, "caption", visible_captions.append)

    def fail_surface() -> None:
        raise RuntimeError("portfolio repository unavailable")

    guarded = render_app._guarded_renderer("today", fail_surface)
    with caplog.at_level(
        logging.ERROR,
        logger="capital_intelligence.render_surfaces",
    ):
        result = guarded()

    assert result is None
    assert visible_errors == [
        "This surface could not be rendered. The application remains online "
        "and the failure has been recorded for diagnosis."
    ]
    assert visible_captions == ["Surface: today · Error class: RuntimeError"]
    assert "primary Streamlit surface failed to render: today" in caplog.text
