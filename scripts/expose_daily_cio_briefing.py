from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected one match in {path}, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app_impl.py",
    '''    page_header(
        "Decision pulse",
        "The system stays quiet until evidence earns a portfolio-level conclusion.",
        "01",
    )
''',
    '''    page_header(
        "Daily CIO briefing",
        (
            "The latest completed CIO conclusion: what changed, why it matters, "
            "the portfolio implication, and the recommended action or deliberate inaction."
        ),
        "01",
    )
''',
)
replace_once(
    "app_impl.py",
    '            "CIO pulse // standby",\n',
    '            "Daily CIO briefing // unavailable",\n',
)
replace_once(
    "app_impl.py",
    '''        signal_panel(
            f"CIO pulse // {status}",
            briefing.get("portfolio_decision") or "Maintain current posture",
            briefing.get("why_it_matters")
            or "No additional portfolio-level conclusion is available.",
            variant="today",
        )
        metric_grid(
''',
    '''        signal_panel(
            f"Daily CIO briefing // {status}",
            briefing.get("portfolio_decision") or "Maintain current posture",
            briefing.get("why_it_matters")
            or "No additional portfolio-level conclusion is available.",
            variant="today",
        )
        st.caption(
            f"Briefing as of {format_datetime(briefing.get('as_of'))} · "
            f"Decision reference {_briefing_identifier(briefing)}"
        )
        metric_grid(
''',
)
replace_once(
    "app_impl.py",
    '            text_card("Signal change", briefing.get("what_changed"))\n',
    '            text_card("What changed", briefing.get("what_changed"))\n',
)
replace_once(
    "app_impl.py",
    '            text_card("Portfolio relevance", briefing.get("why_it_matters"))\n',
    '            text_card("Why it matters", briefing.get("why_it_matters"))\n',
)
replace_once(
    "app_impl.py",
    '                "Opportunity / risk vector",\n',
    '                "Opportunity or risk",\n',
)
replace_once(
    "app_impl.py",
    '                "Capital action",\n',
    '                "Recommended portfolio action",\n',
)
replace_once(
    "app_impl.py",
    '''    page_header(
        "Decision trail",
        (
            "Every conclusion, evaluation, thesis, and paper action remains "
            "visible as governed institutional memory."
        ),
        "01",
    )
''',
    '''    page_header(
        "CIO briefing and decision archive",
        (
            "Every daily CIO briefing, conclusion, evaluation, thesis, and paper "
            "action remains visible as governed institutional memory."
        ),
        "01",
    )
''',
)

replace_once(
    "cio_pending_transactions_ui.py",
    '    st.subheader("CIO Pending Transaction Recommendations")\n',
    '    st.subheader("Paper implementation status")\n',
)
replace_once(
    "cio_pending_transactions_ui.py",
    '''    st.caption(
        f"Paper trading launch: {report['paper_trading_start_label']} · "
        f"Execution state: {str(report.get('execution_state', 'unavailable')).replace('_', ' ').title()} · "
        "Exact canonical CIO construction"
    )
''',
    '''    st.caption(
        "How the latest CIO conclusion translates into governed paper implementation · "
        f"Launch: {report['paper_trading_start_label']} · "
        f"Execution: {str(report.get('execution_state', 'unavailable')).replace('_', ' ').title()}"
    )
''',
)

replace_once(
    "app.py",
    '''# Today is the immediate operating summary: live provider/session state and the exact
# pending CIO implementation are displayed before the narrative decision surface.
''',
    '''# Today leads with the explicit daily CIO briefing and current capital position.
# Provider status and paper implementation follow as supporting operating context.
''',
)
replace_once(
    "app.py",
    '''_source = _source.replace(
    _today_anchor,
    _today_anchor
    + '    _today_construction = _latest("portfolio_construction")\\n'
    + '    render_live_market_status()\\n'
    + '    render_pending_transaction_report(\\n'
    + '        construction=_today_construction,\\n'
    + '        briefing=briefing,\\n'
    + '    )\\n',
    1,
)
''',
    '''_source = _source.replace(
    _today_anchor,
    _today_anchor
    + '    _today_construction = _latest("portfolio_construction")\\n',
    1,
)

_today_operating_context_anchor = (
    '    allocation_bar(cash=totals["cash"], nav=totals["nav"])\\n'
)
if _source.count(_today_operating_context_anchor) != 1:
    raise RuntimeError("Today operating context insertion point is unavailable")
_source = _source.replace(
    _today_operating_context_anchor,
    _today_operating_context_anchor
    + '    page_header(\\n'
    + '        "Live operating context",\\n'
    + '        "Provider coverage and paper implementation supporting today\'s CIO conclusion.",\\n'
    + '        "03",\\n'
    + '    )\\n'
    + '    render_live_market_status()\\n'
    + '    render_pending_transaction_report(\\n'
    + '        construction=_today_construction,\\n'
    + '        briefing=briefing,\\n'
    + '    )\\n',
    1,
)
''',
)

Path("tests/test_cio_briefing_visibility.py").write_text(
    '''from pathlib import Path


def test_today_surface_names_and_prioritizes_daily_cio_briefing() -> None:
    implementation = Path("app_impl.py").read_text(encoding="utf-8")
    assert '"Daily CIO briefing"' in implementation
    assert '"Daily CIO briefing // unavailable"' in implementation
    assert 'f"Daily CIO briefing // {status}"' in implementation
    assert 'text_card("What changed"' in implementation
    assert 'text_card("Why it matters"' in implementation
    assert '"Recommended portfolio action"' in implementation
    assert '"CIO briefing and decision archive"' in implementation


def test_operating_context_follows_briefing_and_capital_position() -> None:
    entrypoint = Path("app.py").read_text(encoding="utf-8")
    assert "Provider status and paper implementation follow" in entrypoint
    anchor = '_today_operating_context_anchor = ('
    assert anchor in entrypoint
    block = entrypoint[entrypoint.index(anchor) :]
    assert '"Live operating context"' in block
    assert block.index("render_live_market_status") < block.index(
        "render_pending_transaction_report"
    )


def test_implementation_report_uses_plain_language() -> None:
    source = Path("cio_pending_transactions_ui.py").read_text(encoding="utf-8")
    assert 'st.subheader("Paper implementation status")' in source
    assert "How the latest CIO conclusion translates" in source
    assert "CIO Pending Transaction Recommendations" not in source
''',
    encoding="utf-8",
)

Path(__file__).unlink()
