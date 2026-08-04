"""Keep CIO-report navigation inside the authenticated Streamlit session.

A raw ``href`` starts a new browser request and therefore a new Streamlit session.
Authentication tokens are session-local, so that navigation can return an
otherwise authenticated user to the login screen. This presentation-only adapter
replaces both report anchors with in-app buttons that update query parameters and
rerun the existing session.
"""

from __future__ import annotations

from functools import wraps
from html import escape
from types import ModuleType
from typing import Any, Mapping


_INSTALLED_STATE_KEY = "_capital_intelligence_cio_report_session_navigation_installed"
_VIEW_QUERY_KEY = "view"
_VIEW_QUERY_VALUE = "cio-report"

_SESSION_NAVIGATION_CSS = """
<style>
.st-key-cio_report_open_control {
    position: relative;
    margin: .5rem 0 .9rem;
}
.st-key-cio_report_open_control .cio-report-link-shell {
    margin: 0 !important;
}
.st-key-cio_report_open_control [data-testid="stButton"] {
    position: absolute;
    inset: 0;
    z-index: 4;
    margin: 0 !important;
}
.st-key-cio_report_open_control [data-testid="stButton"] button {
    width: 100% !important;
    height: 100% !important;
    min-height: 100% !important;
    padding: 0 !important;
    border: 0 !important;
    background: transparent !important;
    color: transparent !important;
    box-shadow: none !important;
    cursor: pointer !important;
    opacity: 0 !important;
}
.st-key-cio_report_open_control:focus-within .cio-report-link-card {
    border-color: rgba(var(--surface-rgb), .5);
    box-shadow: 0 0 0 2px rgba(var(--surface-rgb), .18), 0 14px 34px rgba(0,0,0,.18);
}
.st-key-cio_report_back_control {
    width: fit-content;
    margin: .28rem 0 .38rem;
}
.st-key-cio_report_back_control [data-testid="stButton"] button {
    min-height: 2rem !important;
    padding: .25rem .1rem !important;
    border: 0 !important;
    background: transparent !important;
    color: var(--surface-accent) !important;
    box-shadow: none !important;
    font-size: .72rem !important;
    font-weight: 760 !important;
    text-decoration: none !important;
}
.st-key-cio_report_back_control [data-testid="stButton"] button:hover,
.st-key-cio_report_back_control [data-testid="stButton"] button:focus-visible {
    color: var(--surface-accent) !important;
    text-decoration: underline !important;
    background: transparent !important;
}
</style>
"""


def _set_report_view(streamlit_module: ModuleType, *, open_report: bool) -> None:
    """Change the report route without replacing the authenticated browser session."""

    params = streamlit_module.query_params
    if open_report:
        params[_VIEW_QUERY_KEY] = _VIEW_QUERY_VALUE
    else:
        try:
            del params[_VIEW_QUERY_KEY]
        except (KeyError, TypeError):
            pass
    streamlit_module.rerun()


def _render_authenticated_link(
    detail: ModuleType,
    streamlit_module: ModuleType,
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    mandate: Mapping[str, Any],
    deployed: float,
) -> None:
    decision = detail.trigger._current_report_title(briefing)
    posture, _ = detail._posture(mandate, deployed)
    implementation_state, _, _ = detail._implementation(construction)
    streamlit_module.markdown(_SESSION_NAVIGATION_CSS, unsafe_allow_html=True)
    with streamlit_module.container(key="cio_report_open_control"):
        streamlit_module.markdown(
            (
                '<div class="cio-report-link-shell" data-testid="stExpander"><summary>'
                '<div class="cio-report-link-card">'
                '<span class="cio-report-link-icon" aria-hidden="true">✓</span>'
                '<span class="cio-report-link-copy">'
                '<span class="cio-report-link-kicker">Current CIO report</span>'
                f'<span class="cio-report-link-title">{escape(decision)}</span>'
                f'<span class="cio-report-link-meta">{escape(posture)} · '
                f'{escape(implementation_state)} · Open complete decision record</span>'
                '</span><span class="cio-report-link-arrow" aria-hidden="true">→</span>'
                '</div></summary></div>'
            ),
            unsafe_allow_html=True,
        )
        if streamlit_module.button(
            "View full CIO report",
            key="open_full_cio_report",
            use_container_width=True,
            type="secondary",
        ):
            _set_report_view(streamlit_module, open_report=True)


class _BackAnchorSuppressingProxy:
    """Delegate Streamlit calls while removing the obsolete full-page back anchor."""

    def __init__(self, streamlit_module: ModuleType) -> None:
        self._streamlit = streamlit_module

    def __getattr__(self, name: str) -> object:
        return getattr(self._streamlit, name)

    def markdown(self, content: str, *args: object, **kwargs: object) -> object:
        if "cio-report-back-link" in str(content):
            return None
        return self._streamlit.markdown(content, *args, **kwargs)


def install(detail: ModuleType) -> None:
    """Replace report anchors with session-preserving Streamlit controls."""

    if getattr(detail, _INSTALLED_STATE_KEY, False):
        return

    original_full_report = detail._render_full_report

    def render_link(
        streamlit_module: ModuleType,
        *,
        briefing: Mapping[str, Any] | None,
        construction: Mapping[str, Any] | None,
        mandate: Mapping[str, Any],
        deployed: float,
    ) -> None:
        _render_authenticated_link(
            detail,
            streamlit_module,
            briefing=briefing,
            construction=construction,
            mandate=mandate,
            deployed=deployed,
        )

    @wraps(original_full_report)
    def render_full_report(
        app: ModuleType,
        streamlit_module: ModuleType,
        *,
        briefing: Mapping[str, Any] | None,
        construction: Mapping[str, Any] | None,
        mandate: Mapping[str, Any],
        deployed: float,
    ) -> None:
        streamlit_module.markdown(_SESSION_NAVIGATION_CSS, unsafe_allow_html=True)
        with streamlit_module.container(key="cio_report_back_control"):
            if streamlit_module.button(
                "← Back to Portfolio",
                key="close_full_cio_report",
                type="tertiary",
            ):
                _set_report_view(streamlit_module, open_report=False)
        original_full_report(
            app,
            _BackAnchorSuppressingProxy(streamlit_module),
            briefing=briefing,
            construction=construction,
            mandate=mandate,
            deployed=deployed,
        )

    detail._render_link = render_link
    detail._render_full_report = render_full_report
    setattr(detail, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
