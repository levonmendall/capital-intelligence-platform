from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cio_decision_export import build_cio_decision_export, cio_decision_export_json
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
    assert (
        refinement._current_report_title(None)
        == "Current governed portfolio assessment"
    )


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
    assert any(
        "View current CIO report" in content
        for content, _ in fake_streamlit.markdown_calls
    )
    assert portfolio.st is original_streamlit


def test_download_uses_matching_lineage_and_starts_with_plain_language_summary() -> None:
    decision_id = "decision:mcd"
    cycle_id = "cycle:current"
    briefing = {
        "decision_identifier": decision_id,
        "cycle_identifier": cycle_id,
        "candidate_identifier": "candidate:mcd:2026-08-05",
        "as_of": "2026-08-05T15:27:47+00:00",
        "portfolio_decision": (
            "CIO decision: no material change. "
            "No executable portfolio change is proposed."
        ),
        "what_changed": (
            "Company quality, growth, valuation, momentum, and regime evidence "
            "changed the expected-return estimate"
        ),
        "why_it_matters": (
            "The candidate offers a 38.42% cost-adjusted expected return versus "
            "a 37.00% alternative, with 17.26% expected downside."
        ),
        "opportunity_or_risk": "MCD is ranked #1; quality evidence could deteriorate",
        "confidence": 0.54,
    }
    histories = {
        "cio_decision": (
            {
                "identifier": "decision:klac",
                "candidate_identifier": "candidate:klac:2026-08-05",
                "action": "hold",
                "code_version": "release-1",
            },
            {
                "identifier": decision_id,
                "cycle_identifier": cycle_id,
                "candidate_identifier": "candidate:mcd:2026-08-05",
                "as_of": "2026-08-05T15:27:47+00:00",
                "action": "hold",
                "code_version": "release-1",
                "decision_horizon_days": 365,
                "expected_return": 0.3842,
                "effective_opportunity_cost": 0.37,
                "probability_of_success": 0.75,
            },
        ),
        "decision_evidence_snapshot": (
            {"decision_identifier": "decision:klac", "symbol": "KLAC"},
            {
                "decision_identifier": decision_id,
                "cycle_identifier": cycle_id,
                "snapshot_identifier": "snapshot:mcd",
                "as_of": "2026-08-05T15:27:47+00:00",
                "symbol": "MCD",
                "expected_return": 0.3842,
                "effective_opportunity_cost": 0.37,
                "expected_downside": -0.1726,
                "probability_of_success": 0.75,
                "opportunity_rank": 1,
            },
        ),
        "portfolio_construction": (
            {
                "cycle_identifier": "cycle:older",
                "as_of": "2026-08-05T14:07:09+00:00",
                "trades": [{"symbol": "KLAC"}],
            },
            {
                "cycle_identifier": cycle_id,
                "as_of": "2026-08-05T15:27:47+00:00",
                "trades": [],
            },
        ),
        "decision_evaluation": (),
    }
    app = SimpleNamespace(
        _history=lambda event_type, *, limit: histories[event_type],
        _latest=lambda event_type: histories[event_type][0]
        if histories[event_type]
        else None,
        _diagnostic_environment=lambda: {
            "environment": {
                "headline": "Risk appetite improved",
                "summary": "Equities and credit stabilized.",
                "regime": "constructive growth",
            }
        },
        load_live_market_console=lambda: {
            "status": "connected",
            "market_open": True,
            "quote_count": 15,
            "expected_quote_count": 15,
            "latest_quote_at": "2026-08-05T15:25:00+00:00",
        },
        load_dashboard_data=lambda: SimpleNamespace(readings=None),
    )
    fake_streamlit = _FakeStreamlit()
    captured: dict[str, str] = {}
    portfolio = SimpleNamespace(
        st=fake_streamlit,
        build_cio_decision_export=build_cio_decision_export,
        cio_decision_export_json=cio_decision_export_json,
    )

    def render_report(
        app: object,
        *,
        briefing: object,
        construction: object,
        mandate: object,
        deployed: float,
    ) -> None:
        del mandate, deployed
        bundle = portfolio.build_cio_decision_export(
            cio_decision=app._latest("cio_decision"),
            daily_cio_briefing=briefing,
            decision_evidence_snapshot=app._latest("decision_evidence_snapshot"),
            portfolio_construction=construction,
            decision_evaluation=app._latest("decision_evaluation"),
        )
        captured["json"] = portfolio.cio_decision_export_json(bundle)
        portfolio.st.expander("CIO report", expanded=False)

    portfolio._render_cio_report = render_report
    refinement.install(portfolio)
    original_latest = app._latest
    original_builder = portfolio.build_cio_decision_export
    original_serializer = portfolio.cio_decision_export_json

    portfolio._render_cio_report(
        app,
        briefing=briefing,
        construction=histories["portfolio_construction"][0],
        mandate={},
        deployed=0.0,
    )

    exported = json.loads(captured["json"])
    assert list(exported)[:2] == ["reader_summary", "schema_version"]
    assert exported["decision_identifier"] == decision_id
    assert exported["records"]["cio_decision"]["candidate_identifier"].startswith(
        "candidate:mcd"
    )
    assert exported["records"]["decision_evidence_snapshot"]["symbol"] == "MCD"
    assert "KLAC" not in exported["reader_summary"]["summary"]
    assert "38.4% return after costs" in exported["reader_summary"]["summary"]
    assert "Risk appetite improved" in exported["reader_summary"][
        "current_market_context"
    ]["summary"]
    assert app._latest is original_latest
    assert portfolio.build_cio_decision_export is original_builder
    assert portfolio.cio_decision_export_json is original_serializer


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
