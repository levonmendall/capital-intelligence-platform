from __future__ import annotations

from types import ModuleType

import pytest

import cio_report_detail_runtime as detail


class _StopRequested(BaseException):
    pass


class _FakeStreamlit:
    def __init__(self) -> None:
        self.query_params: dict[str, str] = {}
        self.markdown_calls: list[str] = []
        self.captions: list[str] = []

    def markdown(self, content: str, *, unsafe_allow_html: bool = False) -> None:
        assert unsafe_allow_html is True
        self.markdown_calls.append(content)

    def caption(self, value: object) -> None:
        self.captions.append(str(value))

    def stop(self) -> None:
        raise _StopRequested()


class _FakeApp(ModuleType):
    def __init__(self) -> None:
        super().__init__("fake_app")
        self.headers: list[str] = []
        self.callouts: list[str] = []
        self.metrics: list[object] = []
        self.statuses: list[object] = []
        self.freshness: list[str] = []

    def page_header(self, title: str, description: str, index: str) -> None:
        del description, index
        self.headers.append(title)

    def callout_card(self, title: str, body: object, note: object) -> None:
        del body, note
        self.callouts.append(title)

    def metric_grid(self, rows: object, *, variant: str) -> None:
        assert variant == "portfolio"
        self.metrics.append(rows)

    def status_list(self, rows: object, *, variant: str) -> None:
        assert variant == "portfolio"
        self.statuses.append(rows)

    def render_information_freshness(self, *, briefing: object, surface: str) -> None:
        del briefing
        self.freshness.append(surface)

    def _diagnostic_environment(self):
        return {
            "environment": {
                "headline": "Growth remains supportive",
                "summary": "Inflation is elevated but easing.",
                "review_conditions": [
                    "Long yields change materially",
                    "Long yields change materially",
                ],
            }
        }

    def load_live_market_console(self):
        return {
            "market_open": True,
            "quote_count": 15,
            "expected_quote_count": 15,
        }


def _portfolio(streamlit_module: _FakeStreamlit):
    portfolio = ModuleType("portfolio_first")
    portfolio.st = streamlit_module
    calls: list[str] = []

    def capital_structure(app: object, *, mandate: object):
        del app, mandate
        calls.append("capital")
        return 250000.0, 250000.0, 0.0

    def render_report(
        app: object,
        *,
        briefing: object,
        construction: object,
        mandate: object,
        deployed: float,
    ) -> None:
        del app, briefing, construction, mandate, deployed
        calls.append("inline-report")

    portfolio._capital_structure = capital_structure
    portfolio._render_cio_report = render_report
    return portfolio, calls


def _briefing() -> dict[str, object]:
    return {
        "portfolio_decision": "Hold. No executable portfolio change is proposed.",
        "what_changed": "Expected-return evidence changed.",
        "why_it_matters": "The candidate does not clear the governed hurdle.",
        "opportunity_or_risk": "Analytical coverage remains incomplete.",
        "evidence_that_changes_conclusion": [
            "A superior opportunity clears every threshold",
            "A superior opportunity clears every threshold",
            "Evidence quality deteriorates",
        ],
        "decision_identifier": "decision-1",
        "cycle_identifier": "cycle-1",
        "candidate_identifier": "KLAC",
        "confidence": 0.65,
    }


def test_portfolio_shows_one_direct_link_without_rendering_inline_report() -> None:
    streamlit_module = _FakeStreamlit()
    portfolio, calls = _portfolio(streamlit_module)
    detail.install(portfolio)

    result = portfolio._capital_structure(object(), mandate={"nav": 250000, "cash": 250000})
    portfolio._render_cio_report(
        _FakeApp(),
        briefing=_briefing(),
        construction={"status": "feasible", "trades": [{}]},
        mandate={"nav": 250000, "cash": 250000, "holdings": []},
        deployed=0.0,
    )

    assert result == (250000.0, 250000.0, 0.0)
    assert calls == ["capital"]
    markup = "\n".join(streamlit_module.markdown_calls)
    assert 'href="?view=cio-report"' in markup
    assert 'aria-label="View full CIO report"' in markup
    assert "inline-report" not in calls


def test_dedicated_route_hides_capital_opening_and_renders_complete_report() -> None:
    streamlit_module = _FakeStreamlit()
    streamlit_module.query_params["view"] = "cio-report"
    portfolio, calls = _portfolio(streamlit_module)
    app = _FakeApp()
    detail.install(portfolio)

    result = portfolio._capital_structure(
        app,
        mandate={"nav": 250000, "cash": 250000},
    )
    with pytest.raises(_StopRequested):
        portfolio._render_cio_report(
            app,
            briefing=_briefing(),
            construction={"status": "feasible", "identifier": "construction-1", "trades": [{}]},
            mandate={"nav": 250000, "cash": 250000, "holdings": []},
            deployed=0.0,
        )

    assert result == (250000.0, 250000.0, 0.0)
    assert calls == []
    assert app.headers == [
        "Full CIO report",
        "Decision context",
        "Monitoring and reversal conditions",
        "Decision lineage",
    ]
    assert app.callouts == ["CIO decision"]
    assert app.freshness == ["portfolio"]
    markup = "\n".join(streamlit_module.markdown_calls)
    assert 'href="?"' in markup
    assert markup.count("A superior opportunity clears every threshold") == 1
    assert "Long yields change materially" in markup
    assert any("read-only presentation" in caption for caption in streamlit_module.captions)


def test_report_query_requires_exact_dedicated_view_value() -> None:
    streamlit_module = _FakeStreamlit()
    assert detail.report_requested(streamlit_module) is False
    streamlit_module.query_params["view"] = "history"
    assert detail.report_requested(streamlit_module) is False
    streamlit_module.query_params["view"] = "cio-report"
    assert detail.report_requested(streamlit_module) is True
