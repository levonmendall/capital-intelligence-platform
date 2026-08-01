from __future__ import annotations

import logging
import threading
import time

import app_impl
import live_operating_console
import operating_intelligence_ui
import render_app
import render_nonblocking_data


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


def test_render_entrypoint_installs_nonblocking_provider_lookups() -> None:
    originals = {
        "app_live": app_impl.load_live_market_console,
        "app_economic": app_impl.load_dashboard_data,
        "operating_live": operating_intelligence_ui.load_live_market_console,
        "operating_economic": operating_intelligence_ui.load_dashboard_data,
        "console_live": live_operating_console.load_live_market_console,
    }
    try:
        render_app.prepare_render_data_runtime()

        assert (
            app_impl.load_live_market_console
            is render_nonblocking_data.load_live_market_console_nonblocking
        )
        assert (
            app_impl.load_dashboard_data
            is render_nonblocking_data.load_dashboard_data_nonblocking
        )
        assert (
            operating_intelligence_ui.load_live_market_console
            is render_nonblocking_data.load_live_market_console_nonblocking
        )
        assert (
            operating_intelligence_ui.load_dashboard_data
            is render_nonblocking_data.load_dashboard_data_nonblocking
        )
        assert (
            live_operating_console.load_live_market_console
            is render_nonblocking_data.load_live_market_console_nonblocking
        )
    finally:
        app_impl.load_live_market_console = originals["app_live"]
        app_impl.load_dashboard_data = originals["app_economic"]
        operating_intelligence_ui.load_live_market_console = originals[
            "operating_live"
        ]
        operating_intelligence_ui.load_dashboard_data = originals[
            "operating_economic"
        ]
        live_operating_console.load_live_market_console = originals["console_live"]


def test_background_loader_returns_fallback_without_waiting_for_stalled_provider() -> None:
    release = threading.Event()

    def stalled_supplier() -> str:
        release.wait(2.0)
        return "provider-value"

    loader = render_nonblocking_data._BackgroundLoader[str](
        name="stalled-test-provider",
        supplier=stalled_supplier,
        fallback=lambda: "fallback-value",
        ttl_seconds=60.0,
        initial_wait_seconds=0.01,
    )

    started_at = time.monotonic()
    assert loader.get() == "fallback-value"
    assert time.monotonic() - started_at < 0.25

    release.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if loader.get() == "provider-value":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("background provider result was not published")


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
