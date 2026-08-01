from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import surface_content_refinement as refinement


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdown_values: list[str] = []
        self.caption_values: list[str] = []
        self.write_values: list[object] = []
        self.expander_labels: list[str] = []

    def markdown(self, value: str, **_kwargs: object) -> None:
        self.markdown_values.append(value)

    def caption(self, value: str) -> None:
        self.caption_values.append(value)

    def write(self, value: object) -> None:
        self.write_values.append(value)

    def divider(self) -> None:
        return None

    @contextmanager
    def expander(self, label: str, **_kwargs: object):
        self.expander_labels.append(label)
        yield

    def fragment(self, **_kwargs: object):
        def decorate(function):
            function.__wrapped__ = function
            return function

        return decorate


def _patch_shared_briefing_dependencies(monkeypatch, fake_streamlit) -> None:
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    monkeypatch.setattr(
        refinement.experience,
        "_render_event_field_details",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "_daily_caption",
        lambda _snapshot: "Daily status.",
    )


def test_today_surface_contains_only_current_information_sections(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    _patch_shared_briefing_dependencies(monkeypatch, fake_streamlit)
    item = SimpleNamespace(
        title="Policy guidance changed",
        summary="A regulator changed examination guidance.",
        affected_investments="Banks, cash, Treasuries, and growth equities.",
        impact_channels=("rates", "liquidity", "risk_appetite"),
        what_to_watch="Watch implementation guidance and funding markets.",
    )
    snapshot = SimpleNamespace(records=({},), detail="Current event detail")
    monkeypatch.setattr(
        refinement.concise.base,
        "load_public_event_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "build_today_items",
        lambda _records: (item,),
    )

    refinement.render_today_market_brief(briefing={"portfolio_decision": "hold"})

    section_names = [label.split(" · ", 1)[0] for label in fake_streamlit.expander_labels]
    assert section_names == [
        "WHAT CHANGED",
        "ASSETS IN FOCUS",
        "TRANSMISSION CHANNELS",
        "WHAT TO WATCH NEXT",
    ]
    assert "PORTFOLIO EFFECT" not in section_names
    assert "CIO RESPONSE" not in section_names
    markup = "\n".join(fake_streamlit.markdown_values)
    assert "investment developments" in markup
    assert "Today // current information" in markup


def test_environment_surface_contains_only_backdrop_sections(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    _patch_shared_briefing_dependencies(monkeypatch, fake_streamlit)
    readings = SimpleNamespace(
        inflation_rate=2.6,
        unemployment_rate=4.2,
        federal_funds_rate=4.5,
        yield_curve_spread=0.35,
    )
    dashboard = SimpleNamespace(
        readings=readings,
        data_source="Governed macro source",
    )
    snapshot = SimpleNamespace(records=(), detail="No policy event")
    monkeypatch.setattr(
        refinement.concise.base,
        "load_public_event_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "build_economic_event_items",
        lambda _records: (),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_dashboard_data",
        lambda: dashboard,
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "economic_snapshot_summary",
        lambda _readings: "Inflation is moderating while labor demand remains firm.",
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "economic_investment_implications",
        lambda _readings: (
            ("Rates", "Higher discount rates pressure long-duration assets."),
            ("Growth", "Firm demand supports cyclical earnings."),
        ),
    )

    refinement.render_environment_economic_brief(
        briefing={"portfolio_decision": "hold"}
    )

    section_names = [label.split(" · ", 1)[0] for label in fake_streamlit.expander_labels]
    assert section_names == [
        "ECONOMIC STATE",
        "INVESTMENT TRANSMISSION",
        "ASSET-CLASS SENSITIVITY",
        "WHAT TO MONITOR",
    ]
    assert "PORTFOLIO EFFECT" not in section_names
    assert "CIO RESPONSE" not in section_names
    markup = "\n".join(fake_streamlit.markdown_values)
    assert "Economic and market backdrop" in markup
    assert "Environment // structural conditions" in markup


def test_source_health_is_filtered_to_the_active_surface(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    entries = (
        SimpleNamespace(label="Market quotes", state="Current", detail="Quotes"),
        SimpleNamespace(label="Economic data", state="Current", detail="Macro"),
        SimpleNamespace(label="Public events", state="Current", detail="Events"),
        SimpleNamespace(label="CIO conclusion", state="Current", detail="CIO"),
        SimpleNamespace(label="Portfolio valuation", state="Current", detail="NAV"),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_live_market_console",
        lambda: {},
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_dashboard_data",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "load_public_event_snapshot",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "get_mandate_details",
        lambda _code: {},
    )
    monkeypatch.setattr(
        refinement.concise.base,
        "build_freshness_entries",
        lambda **_kwargs: entries,
    )
    captured: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        refinement.concise.ui,
        "metric_grid",
        lambda metrics, **_kwargs: captured.append(
            tuple(str(label) for label, _value, _detail in metrics)
        ),
    )

    refinement.render_information_freshness(briefing=None, surface="today")
    refinement.render_information_freshness(briefing=None, surface="environment")
    refinement.render_information_freshness(briefing=None, surface="portfolio")

    assert captured == [
        ("Market quotes", "Public events"),
        ("Market quotes", "Economic data"),
        ("CIO conclusion", "Portfolio valuation"),
    ]


def test_install_changes_today_and_environment_but_preserves_other_surfaces(
    monkeypatch,
) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    original_today = object()
    original_environment = object()
    original_portfolio = object()
    original_history = object()
    app = SimpleNamespace(
        render_information_freshness=object(),
        render_today_market_brief=object(),
        render_environment_economic_brief=object(),
        render_today_opportunity_scan=object(),
        _render_today=original_today,
        _render_environment=original_environment,
        _render_portfolio=original_portfolio,
        _render_history=original_history,
    )

    refinement.install(app)

    assert app._render_today is not original_today
    assert app._render_environment is not original_environment
    assert app._render_portfolio is original_portfolio
    assert app._render_history is original_history
    assert app.render_today_market_brief is refinement.render_today_market_brief
    assert (
        app.render_environment_economic_brief
        is refinement.render_environment_economic_brief
    )
