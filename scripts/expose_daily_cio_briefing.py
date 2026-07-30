from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:80]!r}")
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
            "The CIO's concise daily conclusion: what changed, why it matters, "
            "the portfolio implication, and the action or deliberate inaction."
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
    '            f"CIO pulse // {status}",\n',
    '            f"Daily CIO briefing // {status}",\n',
)
replace_once(
    "app_impl.py",
    '''            variant="today",
        )
        metric_grid(
''',
    '''            variant="today",
        )
        st.caption(
            f"Briefing as of {format_datetime(briefing.get('as_of'))} · "
            f"Decision reference {_briefing_identifier(briefing)}"
        )
        metric_grid(
''',
)
replace_once("app_impl.py", '            text_card("Signal change", briefing.get("what_changed"))\n', '            text_card("What changed", briefing.get("what_changed"))\n')
replace_once("app_impl.py", '            text_card("Portfolio relevance", briefing.get("why_it_matters"))\n', '            text_card("Why it matters", briefing.get("why_it_matters"))\n')
replace_once("app_impl.py", '                "Opportunity / risk vector",\n', '                "Opportunity or risk",\n')
replace_once("app_impl.py", '                "Capital action",\n', '                "Recommended portfolio action",\n')
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
    "app.py",
    '''# Today is the immediate operating summary: live provider/session state and the exact
# pending CIO implementation are displayed before the narrative decision surface.
''',
    '''# Today leads with the live provider/session state and the explicit daily CIO
# briefing. The exact pending implementation follows the briefing rather than hiding it.
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
    + '    _today_construction = _latest("portfolio_construction")\\n'
    + '    render_live_market_status()\\n',
    1,
)

_today_report_anchor = (
    '    page_header(\\n'
    '        "Capital position",\\n'
)
if _source.count(_today_report_anchor) != 1:
    raise RuntimeError("Today CIO report insertion point is unavailable")
_source = _source.replace(
    _today_report_anchor,
    '    render_pending_transaction_report(\\n'
    + '        construction=_today_construction,\\n'
    + '        briefing=briefing,\\n'
    + '    )\\n'
    + _today_report_anchor,
    1,
)
''',
)

Path(__file__).unlink()
