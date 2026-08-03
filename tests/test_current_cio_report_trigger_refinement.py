from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import current_cio_report_trigger_refinement as refinement


class _FakeStreamlit:
    def __init__(self) -> None:
        self.labels: list[str] = []
        self.markdown_calls: list[tuple[str, bool]] = []

    def expander(self, label: object, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.labels.append(str(label))
        return object()

    def markdown(self, content: str, *, unsafe_allow_html: bool = False) -> None:
        self.markdown_calls.append((content, unsafe_allow_html))


def test_current_report_title_prefers_governed_report_fields() -> None:
    assert refinement._current_report_title(
        {
            "report_title": "Daily CIO assessment",
            "portfolio_decision": "Maintain current positioning",
        }
    ) == "Daily CIO assessment"
    assert refinement._current_report_title(
        {"portfolio_decision": "Maintain current positioning"}
    ) == "Maintain current positioning"
    assert refinement._current_report_title(None) == "Current governed portfolio assessment"


def test_trigger_shows_current_report_title_and_expandable_link() -> None:
    fake_streamlit = _FakeStreamlit()
    portfolio = SimpleNamespace(st=fake_streamlit)

    def render_report(
        app: object,
        *,
        briefing: object,
        construction: object,
        mandate: object,
        deployed: float,
    ) -> None:
        del app, briefing, construction, mandate, deployed
        portfolio.st.expander("CIO report", expanded=False)

    portfolio._render_cio_report = render_report
    refinement.install(portfolio)
    original_streamlit = portfolio.st

    portfolio._render_cio_report(
        object(),
        briefing={"portfolio_decision": "Maintain cash until evidence improves"},
        construction=None,
        mandate={},
        deployed=0.0,
    )

    assert fake_streamlit.labels == [
        "Current CIO report — Maintain cash until evidence improves"
    ]
    assert any("View current CIO report" in content for content, _ in fake_streamlit.markdown_calls)
    assert portfolio.st is original_streamlit


def test_portfolio_opening_order_is_heading_then_capital_then_report_trigger() -> None:
    source = Path("portfolio_first_ui_refinement.py").read_text(encoding="utf-8")

    capital = source.index("_capital_structure(app_impl, mandate=mandate)")
    report = source.index("_render_cio_report(", capital)
    remaining = source.index("_render_remaining_portfolio(", report)

    assert capital < report < remaining


def test_shared_installer_applies_trigger_after_report_content_refinement() -> None:
    source = Path("opportunity_funnel_ui_refinement.py").read_text(encoding="utf-8")

    backdrop = source.index(
        "cio_report_backdrop_refinement.install(portfolio_first_ui_refinement)"
    )
    trigger = source.index(
        "current_cio_report_trigger_refinement.install(portfolio_first_ui_refinement)"
    )

    assert "import current_cio_report_trigger_refinement" in source
    assert backdrop < trigger
