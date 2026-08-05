"""Keep CIO-report navigation inside the authenticated Streamlit session.

The adapter also renders the exact-lineage decision as a plain-language investment
memo before the technical decision record. It is presentation-only and cannot alter
investment evidence, CIO authority, construction, execution, or portfolio state.
"""

from __future__ import annotations

from functools import wraps
from html import escape
from types import ModuleType
from typing import Any, Callable, Mapping

import cio_investment_memo as investment_memo
from cio_decision_export import (
    build_cio_decision_export,
    cio_decision_export_filename,
    cio_decision_export_json,
    select_cio_decision_records,
)


_INSTALLED_STATE_KEY = "_capital_intelligence_cio_report_session_navigation_installed"
_REPORT_STATE_KEY = "_capital_intelligence_full_cio_report_open"
_VIEW_QUERY_KEY = "view"
_HISTORY_LIMIT = 500

_SESSION_NAVIGATION_CSS = """
<style>
.st-key-cio_report_open_control {
    margin: .5rem 0 .9rem;
    border: 1px solid rgba(var(--surface-rgb), .25);
    border-radius: 1rem;
    background: linear-gradient(145deg, rgba(13,20,34,.94), rgba(8,13,24,.94));
    box-shadow: inset 0 1px 0 rgba(255,255,255,.04), 0 14px 34px rgba(0,0,0,.18);
    overflow: hidden;
}
.st-key-cio_report_open_control .cio-report-link-shell,
.st-key-cio_report_open_control .cio-report-link-card {
    margin: 0 !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    transform: none !important;
}
.st-key-cio_report_open_control [data-testid="stButton"] {
    position: static !important;
    margin: 0 !important;
    padding: 0 .72rem .72rem !important;
}
.st-key-cio_report_open_control [data-testid="stButton"] button {
    position: static !important;
    width: 100% !important;
    min-height: 3rem !important;
    padding: .68rem .9rem !important;
    border: 1px solid rgba(var(--surface-rgb), .42) !important;
    border-radius: .78rem !important;
    background: linear-gradient(135deg, rgba(var(--surface-rgb), .2), rgba(var(--surface-rgb-2), .12)) !important;
    color: #f5f7ff !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.06) !important;
    cursor: pointer !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    font-size: .78rem !important;
    line-height: 1.25 !important;
    font-weight: 800 !important;
}
.st-key-cio_report_open_control [data-testid="stButton"] button:hover,
.st-key-cio_report_open_control [data-testid="stButton"] button:focus-visible {
    border-color: rgba(var(--surface-rgb), .68) !important;
    background: linear-gradient(135deg, rgba(var(--surface-rgb), .3), rgba(var(--surface-rgb-2), .18)) !important;
    box-shadow: 0 0 0 2px rgba(var(--surface-rgb), .15) !important;
    transform: translateY(-1px);
}
.st-key-cio_report_back_control { width: fit-content; margin: .28rem 0 .38rem; }
.st-key-cio_report_back_control [data-testid="stButton"] button {
    min-height: 2.75rem !important;
    padding: .35rem .25rem !important;
    border: 0 !important;
    background: transparent !important;
    color: var(--surface-accent) !important;
    box-shadow: none !important;
    font-size: .72rem !important;
    font-weight: 760 !important;
}
.st-key-cio_report_export_control {
    margin: .35rem 0 .8rem;
    padding: .72rem;
    border: 1px solid rgba(var(--surface-rgb), .24);
    border-radius: .92rem;
    background: linear-gradient(145deg, rgba(13,20,34,.92), rgba(8,13,24,.92));
}
.st-key-cio_report_export_control [data-testid="stDownloadButton"] button {
    width: 100% !important;
    min-height: 3rem !important;
    border: 1px solid rgba(var(--surface-rgb), .48) !important;
    border-radius: .78rem !important;
    background: linear-gradient(135deg, rgba(var(--surface-rgb), .24), rgba(var(--surface-rgb-2), .14)) !important;
    color: #f5f7ff !important;
    font-weight: 800 !important;
    opacity: 1 !important;
    pointer-events: auto !important;
}
@media (max-width: 760px) {
    .st-key-cio_report_open_control [data-testid="stButton"] button,
    .st-key-cio_report_export_control [data-testid="stDownloadButton"] button {
        min-height: 3.15rem !important;
    }
}
</style>
"""


def _remove_legacy_route(streamlit_module: ModuleType) -> None:
    params = getattr(streamlit_module, "query_params", None)
    if params is None:
        return
    try:
        del params[_VIEW_QUERY_KEY]
    except (AttributeError, KeyError, TypeError, ValueError):
        pass


def _set_report_view(streamlit_module: ModuleType, *, open_report: bool) -> None:
    state = streamlit_module.session_state
    if open_report:
        state[_REPORT_STATE_KEY] = True
    else:
        try:
            del state[_REPORT_STATE_KEY]
        except (KeyError, TypeError):
            pass
    _remove_legacy_route(streamlit_module)
    streamlit_module.rerun()


def _session_report_requested(
    streamlit_module: ModuleType,
    legacy_requested: Callable[[ModuleType], bool],
) -> bool:
    try:
        if bool(streamlit_module.session_state.get(_REPORT_STATE_KEY, False)):
            return True
    except (AttributeError, TypeError, ValueError):
        pass
    return bool(legacy_requested(streamlit_module))


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
                f'{escape(implementation_state)}</span>'
                '</span></div></summary></div>'
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


def _latest_record(app: ModuleType, event_type: str) -> Mapping[str, Any] | None:
    loader = getattr(app, "_latest", None)
    if not callable(loader):
        return None
    try:
        value = loader(event_type)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _history_records(app: ModuleType, event_type: str) -> tuple[Mapping[str, Any], ...]:
    loader = getattr(app, "_history", None)
    if not callable(loader):
        return ()
    try:
        values = loader(event_type, limit=_HISTORY_LIMIT)
    except TypeError:
        try:
            values = loader(event_type)
        except (OSError, RuntimeError, TypeError, ValueError):
            return ()
    except (OSError, RuntimeError, ValueError):
        return ()
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, Mapping))


def _candidate_records(
    app: ModuleType,
    event_type: str,
    explicit: Mapping[str, Any] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    if isinstance(explicit, Mapping):
        records.append(explicit)
    latest = _latest_record(app, event_type)
    if latest is not None:
        records.append(latest)
    records.extend(_history_records(app, event_type))
    return tuple(records)


def _decision_bundle(
    app: ModuleType,
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    selected = select_cio_decision_records(
        daily_cio_briefing=briefing,
        cio_decisions=_candidate_records(app, "cio_decision"),
        decision_evidence_snapshots=_candidate_records(
            app,
            "decision_evidence_snapshot",
        ),
        portfolio_constructions=_candidate_records(
            app,
            "portfolio_construction",
            construction,
        ),
        decision_evaluations=_candidate_records(app, "decision_evaluation"),
    )
    return build_cio_decision_export(**selected)


def _render_decision_export(
    app: ModuleType,
    streamlit_module: ModuleType,
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    bundle = _decision_bundle(
        app,
        briefing=briefing,
        construction=construction,
    )
    record_presence = bundle.get("record_presence", {})
    export_available = bool(
        isinstance(record_presence, Mapping) and any(record_presence.values())
    )
    auditability = bundle.get("auditability", {})
    actions = bundle.get("decision_actions", {})

    with streamlit_module.container(key="cio_report_export_control"):
        if isinstance(actions, Mapping) and actions.get("deferred"):
            selected_action = str(actions.get("selected_action") or "").replace(
                "_", " "
            ).title()
            effective_action = str(actions.get("effective_action") or "").replace(
                "_", " "
            ).title()
            streamlit_module.info(
                f"Underlying selected action: {selected_action}. "
                f"Effective current action: {effective_action} — deferred by governed "
                "persistence or cooldown controls."
            )
        if (
            isinstance(auditability, Mapping)
            and auditability.get("status") != "auditable"
        ):
            issues = auditability.get("issues", [])
            issue_text = "; ".join(str(item) for item in issues) or "lineage is incomplete"
            streamlit_module.warning(
                "This export is marked non-auditable and excludes unrelated records: "
                + issue_text
            )
        streamlit_module.download_button(
            "Download decision JSON",
            data=cio_decision_export_json(bundle),
            file_name=cio_decision_export_filename(bundle),
            mime="application/json",
            key="full-cio-report-decision-json-download",
            use_container_width=True,
            disabled=not export_available,
        )
        streamlit_module.caption(
            "Read-only export of records matched to this exact CIO decision and cycle. "
            "Unmatched construction or evaluation records are excluded. It cannot "
            "authorize or execute a trade."
        )
    return bundle


class _BackAnchorSuppressingProxy:
    def __init__(self, streamlit_module: ModuleType) -> None:
        self._streamlit = streamlit_module

    def __getattr__(self, name: str) -> object:
        return getattr(self._streamlit, name)

    def markdown(self, content: str, *args: object, **kwargs: object) -> object:
        if "cio-report-back-link" in str(content):
            return None
        return self._streamlit.markdown(content, *args, **kwargs)


def _market_backdrop(
    detail: ModuleType,
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
) -> str:
    backdrop_module = getattr(detail, "backdrop", None)
    loader = getattr(backdrop_module, "_current_market_backdrop", None)
    if not callable(loader):
        return ""
    try:
        return str(loader(app, briefing) or "")
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""


def install(detail: ModuleType) -> None:
    """Install visible session navigation, exact export, and investment memo."""

    if getattr(detail, _INSTALLED_STATE_KEY, False):
        return

    original_full_report = detail._render_full_report
    original_report_requested = detail.report_requested

    def report_requested(streamlit_module: ModuleType) -> bool:
        return _session_report_requested(
            streamlit_module,
            original_report_requested,
        )

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
        bundle = _render_decision_export(
            app,
            streamlit_module,
            briefing=briefing,
            construction=construction,
        )
        posture, _ = detail._posture(mandate, deployed)
        investment_memo.render_investment_memo(
            streamlit_module,
            bundle,
            market_backdrop=_market_backdrop(detail, app, briefing),
            portfolio_posture=posture,
        )
        original_full_report(
            app,
            _BackAnchorSuppressingProxy(streamlit_module),
            briefing=briefing,
            construction=construction,
            mandate=mandate,
            deployed=deployed,
        )

    detail.report_requested = report_requested
    detail._render_link = render_link
    detail._render_full_report = render_full_report
    setattr(detail, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
