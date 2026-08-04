from __future__ import annotations

from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

import cio_report_session_navigation_runtime as navigation


class _RerunRequested(BaseException):
    pass


class _FakeStreamlit:
    def __init__(self, *, pressed: str = "") -> None:
        self.query_params: dict[str, str] = {}
        self.pressed = pressed
        self.markdown_calls: list[str] = []
        self.button_calls: list[tuple[str, str]] = []
        self.container_keys: list[str] = []

    @contextmanager
    def container(self, *, key: str):
        self.container_keys.append(key)
        yield self

    def markdown(self, content: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.markdown_calls.append(content)

    def button(self, label: str, *, key: str, **kwargs: object) -> bool:
        del kwargs
        self.button_calls.append((label, key))
        return key == self.pressed

    def rerun(self) -> None:
        raise _RerunRequested()


def _detail_module() -> tuple[ModuleType, list[str]]:
    detail = ModuleType("fake_cio_report_detail")
    calls: list[str] = []
    detail.trigger = SimpleNamespace(
        _current_report_title=lambda briefing: str(
            (briefing or {}).get("portfolio_decision", "Current report")
        )
    )
    detail._posture = lambda mandate, deployed: ("Fully in cash", "Cash only")
    detail._implementation = lambda construction: (
        "No construction change queued",
        "Existing capital remains unchanged.",
        0,
    )

    def old_link(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("old-link")

    def old_full_report(
        app: object,
        streamlit_module: object,
        **kwargs: object,
    ) -> None:
        del app, kwargs
        calls.append("full-report")
        streamlit_module.markdown(
            '<a class="cio-report-back-link" href="?">Back</a>',
            unsafe_allow_html=True,
        )
        streamlit_module.markdown("report body", unsafe_allow_html=True)

    detail._render_link = old_link
    detail._render_full_report = old_full_report
    return detail, calls


def test_open_report_uses_query_params_and_rerun_without_href() -> None:
    detail, calls = _detail_module()
    navigation.install(detail)
    streamlit_module = _FakeStreamlit(pressed="open_full_cio_report")
    streamlit_module.query_params["tenant"] = "current"

    with pytest.raises(_RerunRequested):
        detail._render_link(
            streamlit_module,
            briefing={"portfolio_decision": "Hold"},
            construction=None,
            mandate={"holdings": []},
            deployed=0.0,
        )

    assert calls == []
    assert streamlit_module.query_params == {
        "tenant": "current",
        "view": "cio-report",
    }
    assert ("View full CIO report", "open_full_cio_report") in streamlit_module.button_calls
    markup = "\n".join(streamlit_module.markdown_calls)
    assert "href=" not in markup
    assert "Current CIO report" in markup


def test_full_report_suppresses_obsolete_back_anchor() -> None:
    detail, calls = _detail_module()
    navigation.install(detail)
    streamlit_module = _FakeStreamlit()

    detail._render_full_report(
        object(),
        streamlit_module,
        briefing=None,
        construction=None,
        mandate={"holdings": []},
        deployed=0.0,
    )

    assert calls == ["full-report"]
    assert ("← Back to Portfolio", "close_full_cio_report") in streamlit_module.button_calls
    markup = "\n".join(streamlit_module.markdown_calls)
    assert "cio-report-back-link" not in markup
    assert "href=" not in markup
    assert "report body" in markup


def test_back_to_portfolio_removes_only_report_route() -> None:
    detail, calls = _detail_module()
    navigation.install(detail)
    streamlit_module = _FakeStreamlit(pressed="close_full_cio_report")
    streamlit_module.query_params.update(
        {"view": "cio-report", "tenant": "current"}
    )

    with pytest.raises(_RerunRequested):
        detail._render_full_report(
            object(),
            streamlit_module,
            briefing=None,
            construction=None,
            mandate={"holdings": []},
            deployed=0.0,
        )

    assert calls == []
    assert streamlit_module.query_params == {"tenant": "current"}
