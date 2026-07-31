from __future__ import annotations

import streamlit_paper_execution_worker
from security import AuthenticatedPrincipal


def test_streamlit_operator_runs_same_authoritative_pass(monkeypatch) -> None:
    settings = object()
    worker = object()
    captured = {}
    monkeypatch.setattr(
        streamlit_paper_execution_worker,
        "_streamlit_operator_runtime",
        lambda: (settings, worker),
    )

    def run_pass(**kwargs):
        captured.update(kwargs)
        return {
            "status": "operating",
            "paper_execution": {
                "state": "held",
                "real_money_authorized": False,
            },
            "paper_only": True,
            "real_money_authorized": False,
        }

    monkeypatch.setattr(streamlit_paper_execution_worker, "_run_pass", run_pass)

    payload = streamlit_paper_execution_worker._run_streamlit_operator_pass()

    assert captured == {"settings": settings, "worker": worker}
    assert payload["status"] == "operating"
    assert payload["paper_execution"]["state"] == "held"
    assert payload["real_money_authorized"] is False


def test_streamlit_worker_is_not_limited_to_existing_page_payloads() -> None:
    source = open("streamlit_paper_execution_worker.py", encoding="utf-8").read()

    assert "_run_streamlit_operator_pass" in source
    assert "_run_pass(settings=settings, worker=worker)" in source
    assert "del construction, briefing" in source
    assert "build_worker(settings)" in source
    assert "ensure_canonical_portfolio_store" in source
    assert '@st.fragment(run_every="30s")' in source


def test_anonymous_viewer_cannot_start_streamlit_operator(monkeypatch) -> None:
    called = False

    def run_pass():
        nonlocal called
        called = True
        raise AssertionError("anonymous rendering started the paper operator")

    monkeypatch.setattr(
        streamlit_paper_execution_worker,
        "_run_streamlit_operator_pass",
        run_pass,
    )

    streamlit_paper_execution_worker.render_background_paper_execution_worker(
        construction=None,
        briefing=None,
        principal=AuthenticatedPrincipal.anonymous_viewer(),
    )

    assert called is False


def test_only_authenticated_administrator_has_private_streamlit_operator_access() -> None:
    assert not streamlit_paper_execution_worker._has_private_operator_access(None)
    assert not streamlit_paper_execution_worker._has_private_operator_access(
        AuthenticatedPrincipal.anonymous_viewer()
    )
    assert streamlit_paper_execution_worker._has_private_operator_access(
        AuthenticatedPrincipal.testing_system()
    )
