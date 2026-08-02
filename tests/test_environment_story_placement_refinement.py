from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import environment_story_placement_refinement as refinement


def test_retired_environment_grid_does_not_wrap_or_mutate_the_active_renderer() -> None:
    header = object()
    story = object()
    streamlit = object()
    app = SimpleNamespace(
        render_app_header=header,
        surface_story=story,
        st=streamlit,
    )

    refinement.install(app)

    assert app.render_app_header is header
    assert app.surface_story is story
    assert app.st is streamlit
    assert getattr(app, refinement._INSTALLED_STATE_KEY) is True


def test_install_is_idempotent() -> None:
    app = SimpleNamespace()
    refinement.install(app)
    refinement.install(app)
    assert getattr(app, refinement._INSTALLED_STATE_KEY) is True


def test_entrypoints_retain_compatibility_install_after_content_refinement() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import environment_story_placement_refinement" in source
        assert "environment_story_placement_refinement.install(app_impl)" in source
        assert source.index("surface_content_refinement.install(app_impl)") < source.index(
            "environment_story_placement_refinement.install(app_impl)"
        )
