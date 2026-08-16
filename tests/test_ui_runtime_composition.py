from __future__ import annotations

import inspect

import app
import render_app
import ui_runtime_composition


def test_local_and_render_use_one_shared_surface_composition() -> None:
    local_source = inspect.getsource(app.main)
    render_source = inspect.getsource(render_app.main)
    shared_source = inspect.getsource(ui_runtime_composition.install_canonical_surface_composition)

    assert "install_canonical_surface_composition" in local_source
    assert "include_decision_pulse=True" in local_source
    assert "include_history_refinement=False" in local_source
    assert "replace_story_fragments=True" in local_source

    assert "install_canonical_surface_composition" in render_source
    assert "include_decision_pulse=False" in render_source
    assert "include_history_refinement=True" in render_source
    assert "replace_story_fragments=False" in render_source

    assert "portfolio_ui_refinement.install(app_impl)" in shared_source
    assert "surface_route_isolation_runtime.install" in shared_source
