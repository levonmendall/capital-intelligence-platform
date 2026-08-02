from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import environment_story_placement_refinement as refinement


class _FakeStreamlit:
    def fragment(self, *, run_every: str):
        assert run_every == "30s"

        def decorate(function):
            return function

        return decorate


def _app() -> SimpleNamespace:
    return SimpleNamespace(
        _render_today=lambda dependencies: ("old-today", dependencies),
        _render_environment=lambda dependencies: ("old-environment", dependencies),
    )


def test_install_replaces_both_primary_storytelling_surfaces(monkeypatch) -> None:
    app = _app()
    old_today = app._render_today
    old_environment = app._render_environment
    monkeypatch.setattr(refinement, "st", _FakeStreamlit())

    refinement.install(app)

    assert app._render_today is not old_today
    assert app._render_environment is not old_environment
    assert callable(app._render_today)
    assert callable(app._render_environment)
    assert getattr(app, refinement._INSTALLED_KEY) is True


def test_install_is_idempotent(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(refinement, "st", _FakeStreamlit())

    refinement.install(app)
    first_today = app._render_today
    first_environment = app._render_environment
    refinement.install(app)

    assert app._render_today is first_today
    assert app._render_environment is first_environment


def test_module_replaces_repetitive_process_grid_with_distinct_storytelling() -> None:
    source = Path("environment_story_placement_refinement.py").read_text(
        encoding="utf-8"
    )

    assert "process-lens-grid" not in source
    assert "What is moving the investment conversation" in source
    assert "What happened" in source
    assert "Why it matters" in source
    assert "How markets may react" in source
    assert "Environment // structural conditions" in source
    assert "How this backdrop reaches markets" in source
    assert "What would change the view" in source


def test_local_and_render_entrypoints_use_only_final_storytelling_layer() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import environment_story_placement_refinement" in source
        assert "today_story_placement_refinement" not in source
        assert source.index("surface_content_refinement.install(app_impl)") < source.index(
            "environment_story_placement_refinement.install(app_impl)"
        )
