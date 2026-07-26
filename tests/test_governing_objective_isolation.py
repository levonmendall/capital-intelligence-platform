"""Static architecture checks for the single institutional objective."""

from pathlib import Path


ACTIVE_DECISION_FILES = (
    "api/app.py",
    "api/routes/health.py",
    "run_scheduler.py",
    "secure_app.py",
)

FORBIDDEN_ACTIVE_TERMS = (
    "InvestorGoal",
    "InvestmentPolicyProfile",
    "PersonalCIOAlertPlanner",
    "build_personal_cio_brief",
    "objectives_router",
    "personal_cio_history_router",
    "primary_objective",
    "required_return",
    "risk_preference",
)


def test_personal_goal_types_do_not_enter_active_decision_services() -> None:
    for relative_path in ACTIVE_DECISION_FILES:
        source = Path(relative_path).read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_ACTIVE_TERMS:
            assert forbidden not in source, (
                f"{relative_path} must not depend on goal-based input {forbidden}"
            )


def test_goal_routers_are_compatibility_only() -> None:
    route_exports = Path("api/routes/__init__.py").read_text(encoding="utf-8")
    app_source = Path("api/app.py").read_text(encoding="utf-8")

    assert "objectives_router" not in route_exports
    assert "personal_cio_history_router" not in route_exports
    assert "objectives_router" not in app_source
    assert "personal_cio_history_router" not in app_source


def test_governing_objective_is_explicit_in_api_contract() -> None:
    app_source = Path("api/app.py").read_text(encoding="utf-8")

    assert "maximize long-term" in app_source
    assert "compounded portfolio returns" in app_source