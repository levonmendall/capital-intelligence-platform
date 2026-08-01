from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import ui_experience_refinement as refinement


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdown_values: list[str] = []
        self.caption_values: list[str] = []
        self.expander_labels: list[str] = []

    def markdown(self, value: str, **_kwargs: object) -> None:
        self.markdown_values.append(value)

    def caption(self, value: str) -> None:
        self.caption_values.append(value)

    def divider(self) -> None:
        return None

    def write(self, _value: object) -> None:
        return None

    @contextmanager
    def expander(self, label: str, **_kwargs: object):
        self.expander_labels.append(label)
        yield


def test_install_is_idempotent_and_compacts_the_streamlit_shell(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    style_calls: list[bool] = []
    app_impl = SimpleNamespace(
        apply_global_style=lambda *, dark_mode=True: style_calls.append(dark_mode),
        render_information_freshness=object(),
        render_environment_economic_brief=object(),
    )

    refinement.install(app_impl)
    installed_style = app_impl.apply_global_style
    refinement.install(app_impl)

    assert app_impl.apply_global_style is installed_style
    app_impl.apply_global_style(dark_mode=False)

    assert style_calls == [False]
    assert any('[data-testid="stHeader"]' in value for value in fake_streamlit.markdown_values)
    assert any("stHorizontalBlock" in value and "nav-brand-mark" in value for value in fake_streamlit.markdown_values)
    assert app_impl.render_information_freshness is refinement.render_information_freshness
    assert app_impl.render_environment_economic_brief is refinement.render_environment_economic_brief


def test_information_health_surfaces_attention_before_source_detail(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    entries = (
        SimpleNamespace(label="Market", state="Current", detail="Fresh quote set"),
        SimpleNamespace(label="Economy", state="Awaiting refresh", detail="Scheduled refresh"),
        SimpleNamespace(label="Briefing", state="Needs attention", detail="No briefing"),
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


def test_environment_synopsis_does_not_repeat_macro_metric_grid(monkeypatch) -> None:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(refinement, "st", fake_streamlit)
    concise = refinement.concise
    snapshot = SimpleNamespace(records=(), detail="No recent events")
    dashboard = SimpleNamespace(readings=None, data_source="governed macro source")
    monkeypatch.setattr(concise.base, "load_public_event_snapshot", lambda: snapshot)
    monkeypatch.setattr(concise.base, "build_economic_event_items", lambda _records: ())
    monkeypatch.setattr(concise.base, "load_dashboard_data", lambda: dashboard)
    monkeypatch.setattr(concise.base, "economic_snapshot_summary", lambda _readings: "Incomplete")
    monkeypatch.setattr(concise.base, "economic_investment_implications", lambda _readings: ())
    monkeypatch.setattr(concise.base, "_daily_caption", lambda _snapshot: "Daily status.")
    monkeypatch.setattr(concise, "economic_portfolio_lens", lambda _readings: "No standalone action")
    monkeypatch.setattr(concise, "_render_lens_context", lambda **_kwargs: None)
    page_headers: list[str] = []
    lens_titles: list[str] = []
    monkeypatch.setattr(
        concise.ui,
        "page_header",
        lambda title, _description, _index: page_headers.append(title),
    )
    monkeypatch.setattr(
        concise.ui,
        "investment_lens_card",
        lambda **kwargs: lens_titles.append(str(kwargs["title"])),
    )

    def fail_metric_grid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("economic synopsis must not repeat the macro metric grid")

    monkeypatch.setattr(concise.ui, "metric_grid", fail_metric_grid)

    refinement.render_environment_economic_brief(briefing=None)

    assert page_headers == ["Economy and investing"]
    assert lens_titles == ["Economic synopsis"]
