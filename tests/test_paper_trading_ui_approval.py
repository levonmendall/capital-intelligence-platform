"""Static contracts for autonomous and manual paper execution in Streamlit."""

from pathlib import Path

import paper_trading_ui
from security import AuthenticatedPrincipal


ROOT = Path(__file__).resolve().parents[1]


def test_authenticated_app_passes_principal_to_consent_controls() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    secure = (ROOT / "secure_app.py").read_text(encoding="utf-8")

    assert "from paper_trading_ui import render_paper_decision_controls" in app
    assert "render_paper_decision_controls(" in app
    assert 'principal=globals().get("authenticated_principal")' in app
    assert app.count('principal=globals().get("authenticated_principal")') >= 2
    assert '"authenticated_principal": principal' in secure
    assert "paper decision approval insertion point is unavailable" in app


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


def test_public_viewer_does_not_touch_approval_or_execution_runtime(
    monkeypatch,
) -> None:
    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("public rendering touched private paper runtime")

    monkeypatch.setattr(paper_trading_ui, "paper_execution_mode", forbidden)
    monkeypatch.setattr(
        paper_trading_ui,
        "canonical_construction_sha256",
        forbidden,
    )
    monkeypatch.setattr(paper_trading_ui, "approval_database", forbidden)
    monkeypatch.setattr(paper_trading_ui, "attempt_paper_execution", forbidden)

    paper_trading_ui.render_paper_decision_controls(
        construction={
            "request_identifier": "construction:public-test",
            "trades": [{"symbol": "VTI"}],
            "blocks": [],
        },
        briefing={"decision_identifier": "decision:public-test"},
        principal=AuthenticatedPrincipal.anonymous_viewer(),
    )
