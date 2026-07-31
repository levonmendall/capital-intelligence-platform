from __future__ import annotations

from pathlib import Path

import streamlit_paper_execution_worker


def test_streamlit_worker_is_a_read_only_compatibility_projection(monkeypatch) -> None:
    expected = {"state": "completed", "execution_identifier": "paper:1"}
    monkeypatch.setattr(
        streamlit_paper_execution_worker,
        "read_paper_execution_status",
        lambda construction: expected if construction else None,
    )

    payload = streamlit_paper_execution_worker.streamlit_execution_projection(
        {"request_identifier": "construction:1"}
    )

    assert payload["status"] == "read-only"
    assert payload["headless_execution"] == expected
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_active_streamlit_entrypoint_has_no_operator_or_execution_invocation() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    worker = Path("streamlit_paper_execution_worker.py").read_text(encoding="utf-8")

    assert "streamlit_paper_execution_worker" not in app
    assert "render_background_paper_execution_worker" not in app
    assert "run_autonomous_paper_operator" not in worker
    assert "_run_pass" not in worker
    assert "attempt_paper_execution" not in worker
    assert "build_worker" not in worker
