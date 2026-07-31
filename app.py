"""Explicit Streamlit entrypoint for the Capital Intelligence interface."""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any, Callable

import streamlit as st
import premium_ui as _premium_ui

from navigation_ui import install as _install_navigation_ui
from operating_status import load_cio_operating_status


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


_premium_ui = importlib.reload(_premium_ui)
_install_navigation_ui(_premium_ui)
if not hasattr(_premium_ui, "activity_rail"):
    _premium_ui.activity_rail = lambda _items: None
if not hasattr(_premium_ui, "surface_story"):
    _premium_ui.surface_story = lambda _active_page, _steps: None

_original_render_navigation = _premium_ui.render_navigation
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
    operating_status = load_cio_operating_status()
    with _premium_ui.st.sidebar:
        _premium_ui.st.markdown(
            '<div class="sidebar-brand">'
            '<div class="sidebar-mark">CI</div>'
            '<div class="sidebar-brand-title">Capital Intelligence</div>'
            '<div class="sidebar-brand-copy">A continuously operating decision system for one governed portfolio.</div>'
            f'<div class="sidebar-system">{operating_status.label}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        _premium_ui.st.caption(operating_status.detail)
        _premium_ui.st.caption("Four distinct surfaces. One governed portfolio.")
        principal = globals().get("authenticated_principal")
        if (
            os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
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
    profile = _premium_ui.surface_profile(active_page)
    stamp = datetime.now(timezone.utc).strftime("%b %d · %H:%M UTC")
    markup = (
        f'<style>:root{{--surface-accent:{profile.accent};'
        f'--surface-rgb:{profile.accent_rgb};'
        f'--surface-accent-2:{profile.accent_secondary};'
        f'--surface-rgb-2:{profile.accent_secondary_rgb};}}</style>'
        + _premium_ui.compact_header_markup(profile, stamp)
    )
    _premium_ui.st.markdown(markup, unsafe_allow_html=True)


def _safe_allocation_bar(*, cash: float, nav: float) -> None:
    invested = max(float(nav) - float(cash), 0.0)
    deployed = 0.0 if nav <= 0 else min(max(invested / float(nav), 0.0), 1.0)
    markup = (
        '<div class="capital-orbit">'
        f'<div class="capital-ring" style="--deployed:{deployed * 100:.2f}%">'
        f'<div class="capital-ring-value">{deployed:.0%}<span>deployed</span></div></div>'
        '<div class="capital-copy">'
        '<h4>Capital Deployment Orbit</h4>'
        '<p>Capital is allocated by the governed compounding process.</p>'
        '<div class="capital-ledger">'
        f'<div><small>Invested</small><strong>{_premium_ui.format_currency(invested)}</strong></div>'
        f'<div><small>Available cash</small><strong>{_premium_ui.format_currency(cash)}</strong></div>'
        '</div></div></div>'
    )
    _premium_ui.st.markdown(markup, unsafe_allow_html=True)


_premium_ui.render_navigation = _original_render_navigation
_premium_ui.metric_grid = _compatible_metric_grid
_premium_ui.signal_panel = _compatible_signal_panel
_premium_ui.render_sidebar = _safe_render_sidebar
_premium_ui.render_app_header = _safe_render_app_header
_premium_ui.allocation_bar = _safe_allocation_bar

import app_impl as _app_impl
_app_impl = importlib.reload(_app_impl)


def render_application(
    *,
    configure_page: bool = True,
    principal: object | None = None,
    get_mandate_details_fn: Callable[[str], dict[str, Any] | None] | None = None,
    get_portfolio_totals_fn: Callable[[], dict[str, Any]] | None = None,
    get_trade_history_fn: Callable[..., list[dict[str, Any]]] | None = None,
) -> None:
    if configure_page:
        st.set_page_config(
            page_title="Capital Intelligence Platform",
            page_icon="📊",
            layout="wide",
        )
    globals()["authenticated_principal"] = principal
    kwargs: dict[str, object] = {"principal": principal}
    if get_mandate_details_fn is not None:
        kwargs["get_mandate_details_fn"] = get_mandate_details_fn
    if get_portfolio_totals_fn is not None:
        kwargs["get_portfolio_totals_fn"] = get_portfolio_totals_fn
    if get_trade_history_fn is not None:
        kwargs["get_trade_history_fn"] = get_trade_history_fn
    _app_impl.render_application(**kwargs)


if __name__ == "__main__":
    render_application()
