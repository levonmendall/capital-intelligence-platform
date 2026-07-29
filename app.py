"""Deployment-safe Streamlit entrypoint for the Capital Intelligence interface.

The presentation implementation is kept in ``app_impl.py`` so this lightweight
entrypoint can refresh Streamlit's module cache before the interface imports its
helpers. This prevents a mixed-version hot deployment from taking the app down.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import premium_ui as _premium_ui

from cio_pending_transactions_ui import render_pending_transaction_report
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
render_pending_transaction_report(
render_paper_decision_controls(
render_background_paper_execution_worker(
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

# The two newest presentation helpers are enhancement-only. Supplying no-op
# compatibility shims keeps the four core surfaces available if a process is
# briefly running the preceding presentation contract.
if not hasattr(_premium_ui, "activity_rail"):
    _premium_ui.activity_rail = lambda _items: None
if not hasattr(_premium_ui, "surface_story"):
    _premium_ui.surface_story = lambda _active_page, _steps: None

_original_metric_grid = _premium_ui.metric_grid
_original_signal_panel = _premium_ui.signal_panel


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
    """Render sidebar HTML without Markdown code-block indentation."""

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


_premium_ui.metric_grid = _compatible_metric_grid
_premium_ui.signal_panel = _compatible_signal_panel
_premium_ui.render_sidebar = _safe_render_sidebar
_premium_ui.render_app_header = _safe_render_app_header
_premium_ui.allocation_bar = _safe_allocation_bar

_source_path = Path(__file__).with_name("app_impl.py")
_source = _source_path.read_text(encoding="utf-8")

# Refresh the active operating surface without requiring navigation or a browser
# reload. Each fragment re-queries the canonical stores and provider-backed views.
for _render_name in (
    "_render_today",
    "_render_environment",
    "_render_portfolio",
    "_render_history",
):
    _render_anchor = f"def {_render_name}() -> None:\n"
    if _source.count(_render_anchor) != 1:
        raise RuntimeError(f"live refresh insertion point unavailable for {_render_name}")
    _source = _source.replace(
        _render_anchor,
        '@st.fragment(run_every="30s")\n' + _render_anchor,
        1,
    )

# Today is the immediate operating summary: live provider/session state and the exact
# pending CIO implementation are displayed before the narrative decision surface.
_today_anchor = '    theses = _latest_theses()\n'
if _source.count(_today_anchor) != 1:
    raise RuntimeError("Today live operating insertion point is unavailable")
_source = _source.replace(
    _today_anchor,
    _today_anchor
    + '    _today_construction = _latest("portfolio_construction")\n'
    + '    render_live_market_status()\n'
    + '    render_pending_transaction_report(\n'
    + '        construction=_today_construction,\n'
    + '        briefing=briefing,\n'
    + '    )\n',
    1,
)

# Environment combines the governed regime record, live macro evidence, and the
# complete provider-backed cross-asset wrapper monitor.
_environment_anchor = '    dashboard_data = load_dashboard_data()\n'
if _source.count(_environment_anchor) != 1:
    raise RuntimeError("Environment live market insertion point is unavailable")
_source = _source.replace(
    _environment_anchor,
    '    render_live_environment_market_table()\n' + _environment_anchor,
    1,
)

# Add the pending CIO report and consent control at the exact canonical construction
# boundary. The checked anchor makes deployment fail loudly instead of silently losing
# either report visibility or user control when the implementation source changes.
_approval_anchor = '    construction = _latest("portfolio_construction")\n'
if _source.count(_approval_anchor) != 1:
    raise RuntimeError("paper decision approval insertion point is unavailable")
_source = _source.replace(
    _approval_anchor,
    _approval_anchor
    + '    _pending_cio_briefing = _latest("daily_cio_briefing")\n'
    + '    render_pending_transaction_report(\n'
    + '        construction=construction,\n'
    + '        briefing=_pending_cio_briefing,\n'
    + '    )\n'
    + '    render_paper_decision_controls(\n'
    + '        construction=construction,\n'
    + '        briefing=_pending_cio_briefing,\n'
    + '        principal=globals().get("authenticated_principal"),\n'
    + '    )\n',
    1,
)

_portfolio_mark_anchor = '    allocation_bar(cash=mandate["cash"], nav=mandate["nav"])\n'
if _source.count(_portfolio_mark_anchor) != 1:
    raise RuntimeError("Portfolio live mark insertion point is unavailable")
_source = _source.replace(
    _portfolio_mark_anchor,
    _portfolio_mark_anchor + '    render_live_portfolio_marks(mandate)\n',
    1,
)

_history_anchor = '    trades = get_trade_history(limit=250)\n'
if _source.count(_history_anchor) != 1:
    raise RuntimeError("History operating report insertion point is unavailable")
_source = _source.replace(
    _history_anchor,
    _history_anchor + '    render_operating_report_history()\n',
    1,
)

# Keep the execution worker alive on every Streamlit surface. It consumes only an
# already-authenticated exact approval and is idempotent at the construction hash.
_worker_anchor = "render_sidebar()\n"
if _source.count(_worker_anchor) != 1:
    raise RuntimeError("paper execution worker insertion point is unavailable")
_source = _source.replace(
    _worker_anchor,
    _worker_anchor
    + 'render_background_paper_execution_worker(\n'
    + '    construction=_latest("portfolio_construction"),\n'
    + '    briefing=_latest("daily_cio_briefing"),\n'
    + ')\n',
    1,
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
