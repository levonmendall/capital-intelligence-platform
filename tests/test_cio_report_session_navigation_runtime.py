from __future__ import annotations

import json
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

import cio_report_session_navigation_runtime as navigation


class _RerunRequested(BaseException):
    pass


class _FakeStreamlit:
    def __init__(self, *, pressed: str = "") -> None:
        self.query_params: dict[str, str] = {}
        self.session_state: dict[str, object] = {}
        self.pressed = pressed
        self.markdown_calls: list[str] = []
        self.button_calls: list[tuple[str, str]] = []
        self.download_button_calls: list[dict[str, object]] = []
        self.captions: list[str] = []
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

    def download_button(
        self,
        label: str,
        *,
        data: str,
        file_name: str,
        mime: str,
        key: str,
        use_container_width: bool,
        disabled: bool,
    ) -> bool:
        self.download_button_calls.append(
            {
                "label": label,
                "data": data,
                "file_name": file_name,
                "mime": mime,
                "key": key,
                "use_container_width": use_container_width,
                "disabled": disabled,
            }
        )
        return False

    def caption(self, value: object) -> None:
        self.captions.append(str(value))

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
    detail.report_requested = lambda streamlit_module: (
        streamlit_module.query_params.get("view") == "cio-report"
    )

    def old_link(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("old-link")

    def old_full_report(app: object, streamlit_module: object, **kwargs: object) -> None:
        del app, kwargs
        calls.append("full-report")
        streamlit_module.markdown(
            '<a class="cio-report-back-link">Back</a>',
            unsafe_allow_html=True,
        )
        streamlit_module.markdown("report body", unsafe_allow_html=True)

    detail._render_link = old_link
    detail._render_full_report = old_full_report
    return detail, calls


def test_open_report_uses_session_state_and_visible_button() -> None:
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
    assert streamlit_module.query_params == {"tenant": "current"}
    assert streamlit_module.session_state[
        "_capital_intelligence_full_cio_report_open"
    ] is True
    assert detail.report_requested(streamlit_module) is True
    assert ("View full CIO report", "open_full_cio_report") in streamlit_module.button_calls
    markup = "\n".join(streamlit_module.markdown_calls)
    assert "Current CIO report" in markup
    assert "opacity: 0" not in markup
    assert "pointer-events: auto" in markup
    assert "position: absolute" not in markup


def test_legacy_report_query_remains_supported() -> None:
    detail, _ = _detail_module()
    navigation.install(detail)
    streamlit_module = _FakeStreamlit()
    streamlit_module.query_params["view"] = "cio-report"
    assert detail.report_requested(streamlit_module) is True


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
    assert streamlit_module.download_button_calls[0]["disabled"] is True
    markup = "\n".join(streamlit_module.markdown_calls)
    assert "cio-report-back-link" not in markup
    assert "report body" in markup


def test_full_report_exposes_complete_current_decision_json() -> None:
    detail, calls = _detail_module()
    navigation.install(detail)
    streamlit_module = _FakeStreamlit()
    briefing = {
        "decision_identifier": "decision-2026-08-05",
        "cycle_identifier": "cycle-2026-08-05",
        "snapshot_identifier": "snapshot-2026-08-05",
        "as_of": "2026-08-05T15:27:47+00:00",
        "portfolio_decision": "No material change.",
    }
    construction = {
        "decision_identifier": "decision-2026-08-05",
        "as_of": "2026-08-05T15:27:47+00:00",
        "status": "feasible",
        "trades": [{"symbol": "MCD", "side": "buy"}],
    }
    records = {
        "cio_decision": {
            "decision_identifier": "decision-2026-08-05",
            "cycle_identifier": "cycle-2026-08-05",
            "as_of": "2026-08-05T15:27:47+00:00",
        },
        "decision_evidence_snapshot": {
            "snapshot_identifier": "snapshot-2026-08-05",
            "cycle_identifier": "cycle-2026-08-05",
            "as_of": "2026-08-05T15:27:47+00:00",
        },
        "decision_evaluation": {
            "decision_identifier": "decision-2026-08-05",
            "as_of": "2026-08-05T15:27:47+00:00",
            "status": "pending_outcome",
        },
    }
    app = SimpleNamespace(_latest=lambda event_type: records.get(event_type))

    detail._render_full_report(
        app,
        streamlit_module,
        briefing=briefing,
        construction=construction,
        mandate={"holdings": []},
        deployed=0.0,
    )

    assert calls == ["full-report"]
    assert "cio_report_export_control" in streamlit_module.container_keys
    assert len(streamlit_module.download_button_calls) == 1
    download = streamlit_module.download_button_calls[0]
    assert download["label"] == "Download decision JSON"
    assert download["mime"] == "application/json"
    assert download["key"] == "full-cio-report-decision-json-download"
    assert download["use_container_width"] is True
    assert download["disabled"] is False
    assert str(download["file_name"]).startswith(
        "cio-decision-decision-2026-08-05"
    )
    payload = json.loads(str(download["data"]))
    assert payload["record_consistency"]["state"] == "aligned"
    assert all(payload["record_presence"].values())
    assert payload["records"]["daily_cio_briefing"] == briefing
    assert payload["records"]["portfolio_construction"] == construction
    assert payload["authority"]["execution_authority"] is False
    assert payload["authority"]["real_money_authorized"] is False
    assert any("Read-only export" in value for value in streamlit_module.captions)


def test_back_clears_session_state_and_legacy_query() -> None:
    detail, calls = _detail_module()
    navigation.install(detail)
    streamlit_module = _FakeStreamlit(pressed="close_full_cio_report")
    streamlit_module.session_state[
        "_capital_intelligence_full_cio_report_open"
    ] = True
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
    assert "_capital_intelligence_full_cio_report_open" not in (
        streamlit_module.session_state
    )
    assert detail.report_requested(streamlit_module) is False
