from __future__ import annotations

import logging
import threading
import time

import app_impl
import educational_market_briefing_ui
import live_operating_console
import operating_intelligence_ui
import operating_status
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


def test_render_entrypoint_installs_complete_nonblocking_read_boundary(
    monkeypatch,
) -> None:
    originals = {
        "app_latest": app_impl._latest,
        "app_history": app_impl._history,
        "app_theses": app_impl._latest_theses,
        "app_diagnostic": app_impl._diagnostic_environment,
        "app_totals": app_impl.get_portfolio_totals,
        "app_mandate": app_impl.get_mandate_details,
        "app_trades": app_impl.get_trade_history,
        "app_status": app_impl.load_cio_operating_status,
        "app_live": app_impl.load_live_market_console,
        "app_economic": app_impl.load_dashboard_data,
        "operating_mandate": operating_intelligence_ui.get_mandate_details,
        "operating_live": operating_intelligence_ui.load_live_market_console,
        "operating_economic": operating_intelligence_ui.load_dashboard_data,
        "operating_events": operating_intelligence_ui.load_public_event_snapshot,
        "operating_opportunity": operating_intelligence_ui.load_opportunity_scan,
        "operating_accountability": operating_intelligence_ui.load_decision_accountability,
        "event_snapshot": educational_market_briefing_ui.load_public_event_snapshot,
        "status": operating_status.load_cio_operating_status,
        "console_live": live_operating_console.load_live_market_console,
    }
    prewarmed: list[bool] = []
    monkeypatch.setattr(render_app, "prewarm_render_data", lambda: prewarmed.append(True))
    try:
        render_app.prepare_render_data_runtime()

        assert app_impl._latest is render_nonblocking_data.load_journal_latest_nonblocking
        assert app_impl._history is render_nonblocking_data.load_journal_history_nonblocking
        assert app_impl._latest_theses is render_nonblocking_data.load_latest_theses_nonblocking
        assert (
            app_impl._diagnostic_environment
            is render_nonblocking_data.load_diagnostic_environment_nonblocking
        )
        assert (
            app_impl.get_portfolio_totals
            is render_nonblocking_data.get_portfolio_totals_nonblocking
        )
        assert (
            app_impl.get_mandate_details
            is render_nonblocking_data.get_mandate_details_nonblocking
        )
        assert (
            app_impl.get_trade_history
            is render_nonblocking_data.get_trade_history_nonblocking
        )
        assert (
            app_impl.load_cio_operating_status
            is render_nonblocking_data.load_cio_operating_status_nonblocking
        )
        assert (
            app_impl.load_live_market_console
            is render_nonblocking_data.load_live_market_console_nonblocking
        )
        assert (
            app_impl.load_dashboard_data
            is render_nonblocking_data.load_dashboard_data_nonblocking
        )
        assert (
            operating_intelligence_ui.get_mandate_details
            is render_nonblocking_data.get_mandate_details_nonblocking
        )
        assert (
            operating_intelligence_ui.load_public_event_snapshot
            is render_nonblocking_data.load_public_event_snapshot_nonblocking
        )
        assert (
            operating_intelligence_ui.load_opportunity_scan
            is render_nonblocking_data.load_opportunity_scan_nonblocking
        )
        assert (
            operating_intelligence_ui.load_decision_accountability
            is render_nonblocking_data.load_decision_accountability_nonblocking
        )
        assert (
            educational_market_briefing_ui.load_public_event_snapshot
            is render_nonblocking_data.load_public_event_snapshot_nonblocking
        )
        assert (
            operating_status.load_cio_operating_status
            is render_nonblocking_data.load_cio_operating_status_nonblocking
        )
        assert (
            live_operating_console.load_live_market_console
            is render_nonblocking_data.load_live_market_console_nonblocking
        )
        assert prewarmed == [True]
    finally:
        app_impl._latest = originals["app_latest"]
        app_impl._history = originals["app_history"]
        app_impl._latest_theses = originals["app_theses"]
        app_impl._diagnostic_environment = originals["app_diagnostic"]
        app_impl.get_portfolio_totals = originals["app_totals"]
        app_impl.get_mandate_details = originals["app_mandate"]
        app_impl.get_trade_history = originals["app_trades"]
        app_impl.load_cio_operating_status = originals["app_status"]
        app_impl.load_live_market_console = originals["app_live"]
        app_impl.load_dashboard_data = originals["app_economic"]
        operating_intelligence_ui.get_mandate_details = originals[
            "operating_mandate"
        ]
        operating_intelligence_ui.load_live_market_console = originals[
            "operating_live"
        ]
        operating_intelligence_ui.load_dashboard_data = originals[
            "operating_economic"
        ]
        operating_intelligence_ui.load_public_event_snapshot = originals[
            "operating_events"
        ]
        operating_intelligence_ui.load_opportunity_scan = originals[
            "operating_opportunity"
        ]
        operating_intelligence_ui.load_decision_accountability = originals[
            "operating_accountability"
        ]
        educational_market_briefing_ui.load_public_event_snapshot = originals[
            "event_snapshot"
        ]
        operating_status.load_cio_operating_status = originals["status"]
        live_operating_console.load_live_market_console = originals["console_live"]


def test_background_loader_returns_fallback_without_waiting_for_stalled_read() -> None:
    release = threading.Event()

    def stalled_supplier() -> str:
        release.wait(2.0)
        return "store-value"

    loader = render_nonblocking_data._BackgroundLoader[str](
        name="stalled-test-store",
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
        if loader.get() == "store-value":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("background store result was not published")


def test_keyed_background_loader_isolates_stalled_lookup_keys() -> None:
    release = threading.Event()

    def supplier(key: str) -> str:
        if key == "slow":
            release.wait(2.0)
        return f"value:{key}"

    loader = render_nonblocking_data._KeyedBackgroundLoader[str, str](
        name="keyed-test",
        supplier=supplier,
        fallback=lambda key: f"fallback:{key}",
        ttl_seconds=60.0,
        initial_wait_seconds=0.01,
    )

    assert loader.get("slow") == "fallback:slow"
    assert loader.get("fast") == "value:fast"
    release.set()


def test_slow_surface_warning_includes_render_thread_stack(caplog) -> None:
    with caplog.at_level(
        logging.WARNING,
        logger="capital_intelligence.render_surfaces",
    ):
        render_app._log_slow_surface("today", threading.get_ident())

    assert "still running after 8 seconds: today" in caplog.text
    assert "render_thread_stack" in caplog.text
    assert "test_slow_surface_warning_includes_render_thread_stack" in caplog.text


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
