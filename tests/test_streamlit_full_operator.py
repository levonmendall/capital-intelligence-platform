from __future__ import annotations

import streamlit_paper_execution_worker


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
