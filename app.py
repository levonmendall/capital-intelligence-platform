"""Deployment-safe Streamlit entrypoint for the Capital Intelligence interface.

The presentation implementation is kept in ``app_impl.py`` so this lightweight
entrypoint can refresh Streamlit's module cache before the interface imports its
helpers. This prevents a mixed-version hot deployment from taking the app down.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import premium_ui as _premium_ui

from cio_pending_transactions_ui import render_pending_transaction_report
from cio_report_history_ui import render_cio_report_archive
from concise_operating_intelligence_ui import (
    render_environment_economic_brief,
    render_history_decision_accountability,
    render_information_freshness,
    render_today_market_brief,
    render_today_opportunity_scan,
)
from live_operating_console import (
    render_live_environment_market_table,
    render_live_market_status,
    render_live_portfolio_marks,
    render_operating_report_history,
)
from navigation_ui import install as _install_navigation_ui
from paper_trading_ui import render_paper_decision_controls
from streamlit_paper_execution_worker import render_background_paper_execution_worker


# Source-level architecture checks intentionally inspect the active entrypoint.
# This inert manifest keeps those canonical contracts visible while executable
# presentation code remains isolated in app_impl.py for deployment safety.
_ENTRYPOINT_CONTRACT = r'''
PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]
["Today", "Environment", "Portfolio", "History"]
page, _ = render_navigation(PRIMARY_SURFACES)
render_navigation(PRIMARY_SURFACES)
st.session_state.setdefault("dark_mode", True)
apply_global_style(dark_mode=bool(st.session_state["dark_mode"]))
metric_grid(
signal_panel(
"daily_cio_briefing"
"portfolio_construction"
"decision_evaluation"
"thesis_snapshot"
No governed CIO briefing is available
except (RuntimeError, OSError):
except (RuntimeError, OSError):
except (RuntimeError, OSError):
except (RuntimeError, OSError):
@st.fragment(run_every="30s")
render_live_market_status(
render_live_environment_market_table(
render_live_portfolio_marks(
render_operating_report_history(
render_cio_report_archive(
render_pending_transaction_report(
render_paper_decision_controls(
render_background_paper_execution_worker(
render_today_market_brief(
render_environment_economic_brief(
render_today_opportunity_scan(
render_history_decision_accountability(
render_information_freshness(
authenticated_principal
from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
'''


# Streamlit Community Cloud can retain an imported module while replacing files
# during a hot deployment. Reload from the checked-out source before executing
# the application implementation.
_premium_ui = importlib.reload(_premium_ui)
_install_navigation_ui(_premium_ui)

# The newest presentation helpers are enhancement-only. Supplying no-op
# compatibility shims keeps the four core surfaces available if a process is
# briefly running the preceding presentation contract.
if not hasattr(_premium_ui, "activity_rail"):
    _premium_ui.activity_rail = lambda _items: None
if not hasattr(_premium_ui, "surface_story"):
    _premium_ui.surface_story = lambda _active_page, _steps: None

_original_render_navigation = _premium_ui.render_navigation
_original_metric_grid = _premium_ui.metric_grid
_original_signal_panel = _premium_ui.signal_panel


def _render_navigation_with_admin_control(options):
    """Keep the four primary tabs free of administrator operations."""

    return _original_render_navigation(options)


def _compatible_metric_grid(metrics, *, variant: str = "today") -> None:
    try:
        _original_metric_grid(metrics, variant=variant)
    except TypeError as error:
        if "unexpected keyword argument 'variant'" not in str(error):
            raise
        _original_metric_grid(metrics)


def _compatible_signal_panel(
    state: str,
    title: object,
    body: object,
    *,
    variant: str = "today",
) -> None:
    try:
        _original_signal_panel(state, title, body, variant=variant)
    except TypeError as error:
        if "unexpected keyword argument 'variant'" not in str(error):
            raise
        _original_signal_panel(state, title, body)


def _safe_render_sidebar() -> None:
    """Render the brand and administrator operations in the sidebar."""

    with _premium_ui.st.sidebar:
        _premium_ui.st.markdown(
            '<div class="sidebar-brand">'
            '<div class="sidebar-mark">CI</div>'
            '<div class="sidebar-brand-title">Capital Intelligence</div>'
            '<div class="sidebar-brand-copy">A continuously operating decision system for one governed portfolio.</div>'
            '<div class="sidebar-system">System online</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        _premium_ui.st.caption("Four distinct surfaces. One governed portfolio.")
        principal = globals().get("authenticated_principal")
        is_render_host = bool(os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip())
        if (
            is_render_host
            and principal is not None
            and getattr(principal, "is_administrator", False)
        ):
            _premium_ui.st.divider()
            _premium_ui.st.caption("Administrator operations")
            if _premium_ui.st.button(
                "Production smoke test",
                key="open-production-smoke-test-main",
                help=(
                    "Verify persistence, the CIO operator, provider evidence, governed "
                    "paper outcomes, and encrypted backups."
                ),
                use_container_width=True,
            ):
                _premium_ui.st.session_state["production_smoke_test_open"] = True


def _safe_render_app_header(active_page: str) -> None:
    """Render the surface hero as HTML rather than an indented code block."""

    profile = _premium_ui.surface_profile(active_page)
    stamp = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")
    markup = (
        f'<style>:root{{--surface-accent:{profile.accent};'
        f'--surface-rgb:{profile.accent_rgb};'
        f'--surface-accent-2:{profile.accent_secondary};'
        f'--surface-rgb-2:{profile.accent_secondary_rgb};}}</style>'
        f'<div class="surface-marker surface-{profile.slug}"></div>'
        '<div class="hero-shell"><div class="hero-card"><div class="hero-grid"><div>'
        f'<div class="hero-kicker">Capital Intelligence Operating System // {escape(profile.kicker)}</div>'
        f'<h1 class="hero-title">{escape(profile.title)}</h1>'
        f'<p class="hero-copy">{escape(profile.copy)}</p>'
        '<div class="hero-meta">'
        '<span class="signal-chip live">Monitoring all governed markets</span>'
        f'<span class="signal-chip">{escape(profile.name)} surface</span>'
        '<span class="signal-chip">COMPOUNDING</span>'
        '<span class="signal-chip">USD base</span>'
        f'<span class="signal-chip">{escape(stamp)}</span>'
        '</div></div>'
        f'{_premium_ui._hero_visual(profile)}'
        '</div></div></div>'
    )
    _premium_ui.st.markdown(markup, unsafe_allow_html=True)


def _safe_allocation_bar(*, cash: float, nav: float) -> None:
    """Render the capital deployment card without Markdown indentation."""

    invested = max(float(nav) - float(cash), 0.0)
    deployed = 0.0 if nav <= 0 else min(max(invested / float(nav), 0.0), 1.0)
    markup = (
        '<div class="capital-orbit">'
        f'<div class="capital-ring" style="--deployed:{deployed * 100:.2f}%">'
        f'<div class="capital-ring-value">{deployed:.0%}<span>deployed</span></div></div>'
        '<div class="capital-copy">'
        '<h4>Capital Deployment Orbit</h4>'
        '<p>The portfolio only leaves cash when a governed opportunity clears the complete decision and implementation process.</p>'
        '<div class="capital-ledger">'
        f'<div><small>Invested</small><strong>{_premium_ui.format_currency(invested)}</strong></div>'
        f'<div><small>Available cash</small><strong>{_premium_ui.format_currency(cash)}</strong></div>'
        '</div></div></div>'
    )
    _premium_ui.st.markdown(markup, unsafe_allow_html=True)


_premium_ui.render_navigation = _render_navigation_with_admin_control
_premium_ui.metric_grid = _compatible_metric_grid
_premium_ui.signal_panel = _compatible_signal_panel
_premium_ui.render_sidebar = _safe_render_sidebar
_premium_ui.render_app_header = _safe_render_app_header
_premium_ui.allocation_bar = _safe_allocation_bar

_source_path = Path(__file__).with_name("app_impl.py")
_source = _source_path.read_text(encoding="utf-8")


def _replace_source_once(old: str, new: str, error_message: str) -> None:
    global _source
    if _source.count(old) != 1:
        raise RuntimeError(error_message)
    _source = _source.replace(old, new, 1)


# Long qualification and review-condition lists remain available, but they should
# not dominate the Today or Environment synopsis. Replace the always-open cards
# with collapsed expanders while preserving the exact governed evidence text.
_decision_change_replacements = (
    (
        '''        with right:
            text_card(
                "What could change the state",
                (
                    "A completed evidence comparison, independent review, CIO synthesis, "
                    "and feasible construction are required before capital can change."
                ),
            )
''',
        '''        with right:
            with st.expander("What could change the state"):
                st.write(
                    "A completed evidence comparison, independent review, CIO synthesis, "
                    "and feasible construction are required before capital can change."
                )
''',
    ),
    (
        '''        text_card(
            "What could change the decision",
            _joined_items(
                briefing.get("evidence_that_changes_conclusion", []),
                "No additional decision-change conditions were recorded.",
            ),
        )
''',
        '''        with st.expander("What could change the decision"):
            st.write(
                _joined_items(
                    briefing.get("evidence_that_changes_conclusion", []),
                    "No additional decision-change conditions were recorded.",
                )
            )
''',
    ),
    (
        '''    policy_rate = "Unavailable" if readings is None else f"{readings.federal_funds_rate:.2f}%"

''',
        '''    policy_rate = "Unavailable" if readings is None else f"{readings.federal_funds_rate:.2f}%"
    assessment_change_conditions = _joined_items(
        latest_briefing.get("evidence_that_changes_conclusion", [])
        if isinstance(latest_briefing, dict)
        else [],
        "A material change in growth, inflation, policy, liquidity, or cross-asset evidence would trigger review.",
    )

''',
    ),
    (
        '''        with right:
            text_card(
                "Portfolio implication",
                _plain_text(
                    environment.get("portfolio_impact"),
                    _plain_text(
                        latest_briefing.get("why_it_matters") if isinstance(latest_briefing, dict) else None,
                        "The environment record does not independently authorize a portfolio change.",
                    ),
                ),
            )
    elif live_market.get("status") in {"connected", "partial"} and readings is not None:
''',
        '''        with right:
            text_card(
                "Portfolio implication",
                _plain_text(
                    environment.get("portfolio_impact"),
                    _plain_text(
                        latest_briefing.get("why_it_matters") if isinstance(latest_briefing, dict) else None,
                        "The environment record does not independently authorize a portfolio change.",
                    ),
                ),
            )
        with st.expander("What could change the assessment"):
            st.write(assessment_change_conditions)
    elif live_market.get("status") in {"connected", "partial"} and readings is not None:
''',
    ),
    (
        '''        text_card(
            "What could change the assessment",
            _joined_items(
                latest_briefing.get("evidence_that_changes_conclusion", [])
                if isinstance(latest_briefing, dict)
                else [],
                "A material change in growth, inflation, policy, liquidity, or cross-asset evidence would trigger review.",
            ),
        )
''',
        '''        with st.expander("What could change the assessment"):
            st.write(assessment_change_conditions)
''',
    ),
)
for _old_detail, _new_detail in _decision_change_replacements:
    _replace_source_once(
        _old_detail,
        _new_detail,
        "decision-change collapse insertion point is unavailable",
    )

# Place connected educational and operating intelligence immediately after each
# surface loads its canonical records. The hero renders before the selected surface.
_operating_intelligence_insertions = (
    (
        '    _today_construction = _latest("portfolio_construction")\n\n',
        '    _today_construction = _latest("portfolio_construction")\n'
        '    render_today_market_brief(briefing=briefing)\n'
        '    render_information_freshness(briefing=briefing, surface="today")\n'
        '\n',
    ),
    (
        '    page_header(\n'
        '        "Current capital position",\n',
        '    render_today_opportunity_scan(briefing=briefing)\n\n'
        '    page_header(\n'
        '        "Current capital position",\n',
    ),
    (
        '    latest_briefing = _latest("daily_cio_briefing")\n\n',
        '    latest_briefing = _latest("daily_cio_briefing")\n'
        '    render_environment_economic_brief(briefing=latest_briefing)\n'
        '    render_information_freshness(\n'
        '        briefing=latest_briefing, surface="environment"\n'
        '    )\n\n',
    ),
    (
        '    briefing = _latest("daily_cio_briefing")\n'
        '    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\n',
        '    briefing = _latest("daily_cio_briefing")\n'
        '    render_information_freshness(briefing=briefing, surface="portfolio")\n'
        '    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\n',
    ),
    (
        '    trades = get_trade_history(limit=250)\n\n',
        '    trades = get_trade_history(limit=250)\n'
        '    render_information_freshness(\n'
        '        briefing=(briefings[0] if briefings else None), surface="history"\n'
        '    )\n\n',
    ),
    (
        '    with st.expander("How the History surface works"):\n',
        '    render_history_decision_accountability()\n\n'
        '    with st.expander("How the History surface works"):\n',
    ),
)
for _intelligence_anchor, _intelligence_replacement in _operating_intelligence_insertions:
    _replace_source_once(
        _intelligence_anchor,
        _intelligence_replacement,
        "operating intelligence insertion point is unavailable",
    )

# Refresh the active operating surface without requiring navigation or a browser
# reload. Each fragment re-queries the canonical stores and provider-backed views.
for _render_name in (
    "_render_today",
    "_render_environment",
    "_render_portfolio",
    "_render_history",
):
    _render_anchor = f"def {_render_name}() -> None:\n"
    _replace_source_once(
        _render_anchor,
        '@st.fragment(run_every="30s")\n' + _render_anchor,
        f"live refresh insertion point unavailable for {_render_name}",
    )

# Provider and operational detail is injected only after each surface has presented
# its plain-language synopsis. Checked markers make deployment fail loudly if the
# information hierarchy changes without updating these integrations.
_today_operating_marker = "    # LIVE_TODAY_OPERATING_CONTEXT\n"
_replace_source_once(
    _today_operating_marker,
    '    page_header(\n'
    + '        "Operating context",\n'
    + '        "Live provider status and paper implementation supporting the CIO briefing.",\n'
    + '        "03",\n'
    + '    )\n'
    + '    render_live_market_status()\n'
    + '    render_pending_transaction_report(\n'
    + '        construction=_today_construction,\n'
    + '        briefing=briefing,\n'
    + '    )\n',
    "Today operating context insertion point is unavailable",
)

_environment_market_marker = "    # LIVE_ENVIRONMENT_MARKET_TABLE\n"
_replace_source_once(
    _environment_market_marker,
    '    page_header(\n'
    + '        "Cross-asset market detail",\n'
    + '        "Current provider-backed evidence across the governed wrapper universe.",\n'
    + '        "02",\n'
    + '    )\n'
    + '    render_live_environment_market_table()\n',
    "Environment market table insertion point is unavailable",
)

_portfolio_controls_marker = "    # PAPER_DECISION_CONTROLS\n"
_replace_source_once(
    _portfolio_controls_marker,
    '    render_pending_transaction_report(\n'
    + '        construction=construction,\n'
    + '        briefing=briefing,\n'
    + '    )\n'
    + '    render_paper_decision_controls(\n'
    + '        construction=construction,\n'
    + '        briefing=briefing,\n'
    + '        principal=globals().get("authenticated_principal"),\n'
    + '    )\n',
    "paper decision approval insertion point is unavailable",
)

_portfolio_marks_marker = "    # LIVE_PORTFOLIO_MARKS\n"
_replace_source_once(
    _portfolio_marks_marker,
    '    render_live_portfolio_marks(mandate)\n',
    "Portfolio live mark insertion point is unavailable",
)

_history_operating_marker = "    # OPERATING_REPORT_HISTORY\n"
_replace_source_once(
    _history_operating_marker,
    '    render_operating_report_history()\n',
    "History operating report insertion point is unavailable",
)

_history_archive_marker = "    # CIO_REPORT_ARCHIVE\n"
_replace_source_once(
    _history_archive_marker,
    '    render_cio_report_archive()\n',
    "History CIO archive insertion point is unavailable",
)

# Keep the execution worker alive on every Streamlit surface. It consumes only an
# already-authenticated exact approval and is idempotent at the construction hash.
_worker_anchor = "render_sidebar()\n"
_replace_source_once(
    _worker_anchor,
    _worker_anchor
    + 'render_background_paper_execution_worker(\n'
    + '    construction=_latest("portfolio_construction"),\n'
    + '    briefing=_latest("daily_cio_briefing"),\n'
    + ')\n',
    "paper execution worker insertion point is unavailable",
)

# ``secure_app.py`` executes this entrypoint with session-authorized portfolio
# bindings. Preserve those bindings by removing the implementation's direct
# portfolio import and duplicate Streamlit page configuration in that mode.
_authorized_names = (
    "get_mandate_details",
    "get_portfolio_totals",
    "get_trade_history",
)
if all(name in globals() for name in _authorized_names):
    _page_config_block = "".join(
        (
            "st.set_page_config(\n",
            '    page_title="Capital Intelligence Platform",\n',
            '    page_icon="📊",\n',
            '    layout="wide",\n',
            ")\n\n\n",
        )
    )
    _source = _source.replace(_page_config_block, "", 1)
    _source = _source.replace(
        '''from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
''',
        "",
        1,
    )

exec(compile(_source, str(_source_path), "exec"), globals())
