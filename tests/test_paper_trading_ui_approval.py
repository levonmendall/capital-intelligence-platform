"""Static contracts for user-approved paper execution in Streamlit."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_authenticated_app_passes_principal_to_consent_controls() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    secure = (ROOT / "secure_app.py").read_text(encoding="utf-8")

    assert "from paper_trading_ui import render_paper_decision_controls" in app
    assert "render_paper_decision_controls(" in app
    assert 'principal=globals().get("authenticated_principal")' in app
    assert '"authenticated_principal": principal' in secure
    assert "paper decision approval insertion point is unavailable" in app


def test_consent_surface_is_exact_and_paper_only() -> None:
    ui = (ROOT / "paper_trading_ui.py").read_text(encoding="utf-8")
    worker = (ROOT / "run_approved_paper_execution.py").read_text(encoding="utf-8")

    assert "Approve for paper execution" in ui
    assert "Decline implementation" in ui
    assert "Revoke paper approval" in ui
    assert "canonical_construction_sha256" in ui
    assert "write=True" in ui
    assert "require_user_approved_paper_decision" in worker
    assert "run_multi_asset_paper_execution" in worker
    assert '"real_money_authorized": False' in worker
