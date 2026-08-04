"""Give the Portfolio CIO report an explicit current-report expansion trigger.

Presentation only. This module changes the report trigger label and styling; it does
not alter evidence, CIO authority, portfolio construction, execution, or state.
"""

from __future__ import annotations

from functools import wraps
from types import ModuleType
from typing import Any, Mapping


_INSTALLED_STATE_KEY = "_capital_intelligence_current_cio_report_trigger_installed"

_TRIGGER_CSS = """
<style>
/* The capital structure remains immediately above this single report trigger. */
div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary p {
    min-width: 0 !important;
}

div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary p::after {
    content: "View current CIO report";
    display: block;
    margin-top: .24rem;
    color: var(--surface-accent);
    font-size: .66rem;
    line-height: 1.25;
    font-weight: 760;
    letter-spacing: .025em;
    text-decoration: underline;
    text-decoration-thickness: 1px;
    text-underline-offset: .17rem;
}

div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary:hover p::after,
div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary:focus-visible p::after {
    text-decoration-thickness: 2px;
}

@media (max-width: 760px) {
    div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary p {
        font-size: .84rem !important;
    }

    div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary p::after {
        font-size: .62rem;
    }
}
</style>
"""


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _truncate(value: str, limit: int = 76) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip(" .,;:–—-") + "…"


def _current_report_title(briefing: Mapping[str, Any] | None) -> str:
    """Return the clearest current governed report title available."""

    if isinstance(briefing, Mapping):
        for field_name in (
            "report_title",
            "title",
            "headline",
            "portfolio_decision",
            "action",
        ):
            value = _clean(briefing.get(field_name))
            if value:
                return _truncate(value)
    return "Current governed portfolio assessment"


class _StreamlitReportTriggerProxy:
    """Delegate to Streamlit while refining only the CIO report expander."""

    def __init__(self, streamlit_module: ModuleType, report_title: str) -> None:
        self._streamlit = streamlit_module
        self._report_title = report_title
        self._styled = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._streamlit, name)

    def expander(self, label: object, *args: object, **kwargs: object) -> object:
        if str(label) != "CIO report":
            return self._streamlit.expander(label, *args, **kwargs)
        if not self._styled:
            self._streamlit.markdown(_TRIGGER_CSS, unsafe_allow_html=True)
            self._styled = True
        refined_label = f"Current CIO report — {self._report_title}"
        return self._streamlit.expander(refined_label, *args, **kwargs)


def install(portfolio_first: ModuleType) -> None:
    """Install the current-report title and expandable-link presentation once."""

    if getattr(portfolio_first, _INSTALLED_STATE_KEY, False):
        return

    original = portfolio_first._render_cio_report

    @wraps(original)
    def render_cio_report(
        app: ModuleType,
        *,
        briefing: Mapping[str, Any] | None,
        construction: Mapping[str, Any] | None,
        mandate: Mapping[str, Any],
        deployed: float,
    ) -> None:
        original_streamlit = portfolio_first.st
        portfolio_first.st = _StreamlitReportTriggerProxy(
            original_streamlit,
            _current_report_title(briefing),
        )
        try:
            original(
                app,
                briefing=briefing,
                construction=construction,
                mandate=mandate,
                deployed=deployed,
            )
        finally:
            portfolio_first.st = original_streamlit

    portfolio_first._render_cio_report = render_cio_report
    setattr(portfolio_first, _INSTALLED_STATE_KEY, True)

    # Production portfolio_first exposes the capital renderer. Unit tests for
    # this isolated trigger intentionally use a smaller fake module, so keep
    # their scope unchanged while attaching the dedicated route in the app.
    if hasattr(portfolio_first, "_capital_structure"):
        import cio_report_detail_runtime

        cio_report_detail_runtime.install(portfolio_first)


__all__ = ["install", "_current_report_title"]
