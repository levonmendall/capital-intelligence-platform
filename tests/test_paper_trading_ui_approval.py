"""Behavioral contracts for read-only paper state in Streamlit."""

from pathlib import Path

import paper_trading_ui
from paper_execution_runtime import PaperExecutionMode
from security import AuthenticatedPrincipal


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_paper_surface_only_reads_headless_status(monkeypatch) -> None:
    observed = {}

    def read_status(construction):
        observed["construction"] = construction
        return {"state": "completed", "detail": "reconciled"}

    monkeypatch.setattr(paper_trading_ui, "read_paper_execution_status", read_status)
    monkeypatch.setattr(
        paper_trading_ui,
        "paper_execution_mode",
        lambda: PaperExecutionMode.AUTOMATIC,
    )

    construction = {
        "request_identifier": "construction:read-only",
        "trades": [{"symbol": "VTI"}],
        "blocks": [],
    }
    mode, status = paper_trading_ui.paper_execution_view(construction)

    assert observed["construction"] == construction
    assert mode is PaperExecutionMode.AUTOMATIC
    assert status == {"state": "completed", "detail": "reconciled"}


def test_streamlit_paper_surface_imports_no_mutation_authority() -> None:
    ui = (ROOT / "paper_trading_ui.py").read_text(encoding="utf-8")

    for forbidden in (
        "attempt_paper_execution",
        "SQLitePaperDecisionApprovalStore",
        ".approve(",
        ".conclude(",
        "Approve for paper execution",
        "Pause this paper implementation",
        "Resume autonomous paper execution",
    ):
        assert forbidden not in ui
    assert "read_paper_execution_status" in ui
    assert "sole implementation authority" in ui


def test_headless_operator_remains_the_render_execution_process() -> None:
    supervisor = (ROOT / "run_render_service.py").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert 'command=(python, "run_autonomous_paper_operator.py", "--loop")' in supervisor
    assert "attempt_paper_execution" not in app
