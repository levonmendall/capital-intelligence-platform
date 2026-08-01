from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import ui_experience_refinement as refinement


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdown_values: list[str] = []
        self.caption_values: list[str] = []
        self.write_values: list[object] = []
        self.expander_labels: list[str] = []
        self.expander_expanded: list[bool] = []

    def markdown(self, value: str, **_kwargs: object) -> None:
        self.markdown_values.append(value)

    def caption(self, value: str) -> None:
        self.caption_values.append(value)

    def divider(self) -> None:
        return None

    def write(self, value: object) -> None:
        self.write_values.append(value)

    @contextmanager
    def expander(self, label: str, **kwargs: object):
        self.expander_labels.append(label)
        self.expander_expanded.append(bool(kwargs.get("expanded", False)))
        yield


def test_install_is_idempotent_and_compacts_the_streamlit_shell(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    style_calls: list[bool] = []
    app_impl = SimpleNamespace(
        apply_global_style=lambda *, dark_mode=True: style_calls.append(dark_mode),
        render_information_freshness=object(),
        render_today_market_brief=object(),
        render_environment_economic_brief=object(),
    )

    refinement.install(app_impl)
    installed_style = app_impl.apply_global_style
    refinement.install(app_impl)

    assert app_impl.apply_global_style is installed_style
    app_impl.apply_global_style(dark_mode=False)

    assert style_calls == [False]
    assert any(
        '[data-testid="stHeader"]' in value
        for value in fake_streamlit.markdown_values
    )
    assert any(
        "stHorizontalBlock" in value and "nav-brand-mark" in value
        for value in fake_streamlit.markdown_values
    )
    assert app_impl.render_information_freshness is refinement.render_information_freshness
    assert app_impl.render_today_market_brief is refinement.render_today_market_brief
    assert (
        app_impl.render_environment_economic_brief
        is refinement.render_environment_economic_brief
    )


def test_information_health_surfaces_attention_before_source_detail(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    entries = (
        SimpleNamespace(label="Market", state="Current", detail="Fresh quote set"),
        SimpleNamespace(
            label="Economy",
            state="Awaiting refresh",
            detail="Scheduled refresh",
        ),
        SimpleNamespace(
            label="Briefing",
            state="Needs attention",
            detail="No briefing",
        ),
    )
    base = refinement.concise.base
    monkeypatch.setattr(base, "load_live_market_console", lambda: {})
    monkeypatch.setattr(base, "load_dashboard_data", lambda: SimpleNamespace())
    monkeypatch.setattr(base, "load_public_event_snapshot", lambda: SimpleNamespace())
    monkeypatch.setattr(base, "get_mandate_details", lambda _code: {})
    monkeypatch.setattr(base, "build_freshness_entries", lambda **_kwargs: entries)
    monkeypatch.setattr(base, "_schedule_label", lambda: "daily close")
    rendered_metrics: list[tuple[object, str]] = []
    monkeypatch.setattr(
        refinement.concise.ui,
        "metric_grid",
        lambda values, *, variant: rendered_metrics.append((values, variant)),
    )

    refinement.render_information_freshness(briefing=None, surface="portfolio")

    markup = "\n".join(fake_streamlit.markdown_values)
    assert 'role="status"' in markup
    assert "Some information needs attention" in markup
    assert "1 current · 1 refreshing · 1 need attention" in markup
    assert fake_streamlit.expander_labels == ["Source freshness and timestamps"]
    assert rendered_metrics and rendered_metrics[0][1] == "portfolio"


def test_today_synopsis_uses_five_collapsed_icon_sections(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    concise = refinement.concise
    record = {"source_url": "https://example.test/source"}
    snapshot = SimpleNamespace(records=(record,), detail="Current event detail")
    item = SimpleNamespace(
        title="Bank agencies issue a joint statement",
        summary="The agencies changed examination guidance.",
        affected_investments="Cash, Treasuries, banks, and growth equities.",
        portfolio_lens="The event does not independently justify a trade.",
        what_to_watch="Watch implementation guidance and funding markets.",
        source_type="Regulatory",
        source="Federal agency",
        published_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(concise.base, "load_public_event_snapshot", lambda: snapshot)
    monkeypatch.setattr(concise.base, "build_today_items", lambda _records: (item,))
    monkeypatch.setattr(concise.base, "_matching_record", lambda _item, _records: record)
    monkeypatch.setattr(
        concise.base,
        "_record_source_url",
        lambda _record: "https://example.test/source",
    )
    monkeypatch.setattr(concise.base, "_daily_caption", lambda _snapshot: "Daily status.")
    monkeypatch.setattr(concise, "_decision_reference", lambda _briefing: "decision:1")
    page_headers: list[str] = []
    monkeypatch.setattr(
        concise.ui,
        "page_header",
        lambda title, _description, _index: page_headers.append(title),
    )

    def fail_static_card(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the synopsis must use section expanders, not a static lens card")

    monkeypatch.setattr(concise.ui, "investment_lens_card", fail_static_card)

    refinement.render_today_market_brief(briefing=None)

    assert page_headers == ["Investment world today"]
    section_names = [label.split(" · ", 1)[0] for label in fake_streamlit.expander_labels]
    assert section_names == [
        "WHAT CHANGED",
        "WHY INVESTORS CARE",
        "PORTFOLIO EFFECT",
        "CIO RESPONSE",
        "WHAT TO WATCH NEXT",
    ]
    assert fake_streamlit.expander_expanded == [False] * 5
    assert not any("Explore today's investment context" in label for label in fake_streamlit.expander_labels)
    markup = "\n".join(fake_streamlit.markdown_values)
    for marker in (
        "lens-section-change",
        "lens-section-investors",
        "lens-section-portfolio",
        "lens-section-cio",
        "lens-section-watch",
    ):
        assert marker in markup


def test_environment_synopsis_uses_sections_without_repeating_macro_grid(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    concise = refinement.concise
    snapshot = SimpleNamespace(records=(), detail="No recent events")
    dashboard = SimpleNamespace(readings=None, data_source="governed macro source")
    monkeypatch.setattr(concise.base, "load_public_event_snapshot", lambda: snapshot)
    monkeypatch.setattr(concise.base, "build_economic_event_items", lambda _records: ())
    monkeypatch.setattr(concise.base, "load_dashboard_data", lambda: dashboard)
    monkeypatch.setattr(
        concise.base,
        "economic_snapshot_summary",
        lambda _readings: "Incomplete",
    )
    monkeypatch.setattr(
        concise.base,
        "economic_investment_implications",
        lambda _readings: (),
    )
    monkeypatch.setattr(concise.base, "_daily_caption", lambda _snapshot: "Daily status.")
    monkeypatch.setattr(
        concise,
        "economic_portfolio_lens",
        lambda _readings: "No standalone action",
    )
    monkeypatch.setattr(concise, "_decision_reference", lambda _briefing: "decision:1")
    page_headers: list[str] = []
    monkeypatch.setattr(
        concise.ui,
        "page_header",
        lambda title, _description, _index: page_headers.append(title),
    )

    def fail_metric_grid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("economic synopsis must not repeat the macro metric grid")

    def fail_static_card(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the synopsis must use section expanders, not a static lens card")

    monkeypatch.setattr(concise.ui, "metric_grid", fail_metric_grid)
    monkeypatch.setattr(concise.ui, "investment_lens_card", fail_static_card)

    refinement.render_environment_economic_brief(briefing=None)

    assert page_headers == ["Economy and investing"]
    section_names = [label.split(" · ", 1)[0] for label in fake_streamlit.expander_labels]
    assert section_names == [
        "WHAT CHANGED",
        "WHY INVESTORS CARE",
        "PORTFOLIO EFFECT",
        "CIO RESPONSE",
        "WHAT TO WATCH NEXT",
    ]
    assert fake_streamlit.expander_expanded == [False] * 5
    assert not any(
        "Explore the economic investment context" in label
        for label in fake_streamlit.expander_labels
    )
