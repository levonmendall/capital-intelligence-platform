"""Deployment-safe Streamlit entrypoint for the Capital Intelligence interface.

The presentation implementation is kept in ``app_impl.py`` so this lightweight
entrypoint can refresh Streamlit's module cache before the interface imports its
helpers. This prevents a mixed-version hot deployment from taking the app down.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import premium_ui as _premium_ui


# Streamlit Community Cloud can retain an imported module while replacing files
# during a hot deployment. Reload from the checked-out source before executing
# the application implementation.
_premium_ui = importlib.reload(_premium_ui)

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


_premium_ui.metric_grid = _compatible_metric_grid
_premium_ui.signal_panel = _compatible_signal_panel

_source_path = Path(__file__).with_name("app_impl.py")
_source = _source_path.read_text(encoding="utf-8")

# ``secure_app.py`` executes this entrypoint with session-authorized portfolio
# bindings. Preserve those bindings by removing the implementation's direct
# portfolio import and duplicate Streamlit page configuration in that mode.
_authorized_names = (
    "get_mandate_details",
    "get_portfolio_totals",
    "get_trade_history",
)
if all(name in globals() for name in _authorized_names):
    _source = _source.replace(
        '''st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


''',
        "",
        1,
    )
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
