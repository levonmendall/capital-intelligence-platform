"""Static contracts for autonomous and manual paper execution in Streamlit."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_authenticated_app_passes_principal_to_consent_controls() -> None:
    implementation = (ROOT / "app_impl.py").read_text(encoding="utf-8")
    secure = (ROOT / "secure_app.py").read_text(encoding="utf-8")

    assert "from paper_trading_ui import render_paper_decision_controls" in implementation
    assert "render_paper_decision_controls(" in implementation
    assert "principal=principal" in implementation
    assert 'get_mandate_details_fn=bindings["get_mandate_details"]' in secure
    assert 'get_portfolio_totals_fn=bindings["get_portfolio_totals"]' in secure
    assert 'get_trade_history_fn=bindings["get_trade_history"]' in secure
    assert "exec(compile" not in secure

def test_paper_surface_is_exact_paper_only_and_auto_refreshing() -> None:
    ui = (ROOT / "paper_trading_ui.py").read_text(encoding="utf-8")
    worker = (ROOT / "run_approved_paper_execution.py").read_text(encoding="utf-8")

    assert "Approve for paper execution" in ui
    assert "Decline implementation" in ui
    assert "Revoke paper approval" in ui
    assert "canonical_construction_sha256" in ui
    assert "write=True" in ui
    assert '@st.fragment(run_every="5s")' in ui
    assert 'st.toast("Paper transaction completed."' in ui
    assert "Autonomous paper execution" in ui
    assert "Pause this paper implementation" in ui
    assert "Resume autonomous paper execution" in ui
    assert "require_user_approved_paper_decision" in worker
    assert "run_multi_asset_paper_execution" in worker
    assert "Paper transaction completed" in worker
    assert "AlertTopic.IMPLEMENTATION" in worker
    assert "completion_notification_delivery_ids" in worker
    assert '"real_money_authorized": False' in worker
