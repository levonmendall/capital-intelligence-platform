from __future__ import annotations

from types import ModuleType

import surface_route_isolation_runtime as isolation


def _modules(selected: dict[str, str]):
    app = ModuleType("app_impl")
    story = ModuleType("story_ui")
    calls: list[str] = []

    def render_navigation(_options):
        return selected["page"], True

    def fragment_today(_dependencies):
        calls.append("fragment-today")

    def fragment_environment(_dependencies):
        calls.append("fragment-environment")

    def render_today(_app, _dependencies):
        calls.append("today")
        return "today-result"

    def render_environment(_app, _dependencies):
        calls.append("environment")
        return "environment-result"

    app.render_navigation = render_navigation
    app._render_today = fragment_today
    app._render_environment = fragment_environment
    story._render_today = render_today
    story._render_environment = render_environment
    return app, story, calls


def test_selected_surface_owns_story_rendering(monkeypatch) -> None:
    monkeypatch.setattr(isolation.st, "session_state", {})
    selected = {"page": "Today"}
    app, story, calls = _modules(selected)

    isolation.install(app, story, replace_story_fragments=True)
    assert app.render_navigation(["Today", "Environment"]) == ("Today", True)

    assert app._render_today(object()) == "today-result"
    assert app._render_environment(object()) is None
    assert calls == ["today"]

    selected["page"] = "Environment"
    assert app.render_navigation(["Today", "Environment"]) == ("Environment", True)
    assert app._render_today(object()) is None
    assert app._render_environment(object()) == "environment-result"
    assert calls == ["today", "environment"]


def test_render_targets_are_explicit_and_follow_final_story_binding(monkeypatch) -> None:
    monkeypatch.setattr(isolation.st, "session_state", {})
    selected = {"page": "Today"}
    app, story, calls = _modules(selected)

    isolation.install(app, story)
    app.render_navigation(["Today", "Environment"])

    today_target = getattr(
        app._render_today,
        "_capital_intelligence_render_sync_target",
    )
    environment_target = getattr(
        app._render_environment,
        "_capital_intelligence_render_sync_target",
    )
    assert today_target(object()) == "today-result"
    assert environment_target(object()) is None

    def replacement_today(_app, _dependencies):
        calls.append("replacement-today")
        return "replacement-result"

    story._render_today = replacement_today
    assert today_target(object()) == "replacement-result"
    assert calls == ["today", "replacement-today"]


def test_stale_environment_callback_is_suppressed_after_navigation(monkeypatch) -> None:
    monkeypatch.setattr(isolation.st, "session_state", {})
    selected = {"page": "Environment"}
    app, story, calls = _modules(selected)

    isolation.install(app, story)
    app.render_navigation(["Today", "Environment", "Portfolio", "History"])
    stale_environment = story._render_environment

    assert stale_environment(app, object()) == "environment-result"
    selected["page"] = "Portfolio"
    app.render_navigation(["Today", "Environment", "Portfolio", "History"])

    assert stale_environment(app, object()) is None
    assert calls == ["environment"]
