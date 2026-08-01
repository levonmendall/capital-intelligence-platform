from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import environment_story_placement_refinement as refinement


class _FakeStreamlit:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls

    def markdown(self, value: str, **kwargs: object) -> None:
        self.calls.append(("markdown", value, kwargs))

    @contextmanager
    def expander(self, label: str, *args: object, **kwargs: object):
        self.calls.append(("expander", label, args, kwargs))
        yield


def _app(calls: list[tuple[object, ...]]) -> SimpleNamespace:
    streamlit = _FakeStreamlit(calls)

    def render_header(page: str) -> None:
        calls.append(("header", page))

    def render_story(page: str, steps: object) -> None:
        calls.append(("story", page, tuple(steps)))

    return SimpleNamespace(
        render_app_header=render_header,
        surface_story=render_story,
        st=streamlit,
    )


def test_environment_story_is_rendered_after_header_in_horizontal_layout() -> None:
    calls: list[tuple[object, ...]] = []
    app = _app(calls)

    refinement.install(app)
    app.render_app_header("Environment")

    assert calls[0] == ("header", "Environment")
    assert calls[1][0] == "markdown"
    css = str(calls[1][1])
    assert ".surface-story.story-environment" in css
    assert "repeat(4" in css
    assert "overflow-x: auto" in css
    assert "scroll-snap-type: x proximity" in css
    assert "border-radius: 16px" in css
    assert calls[2] == (
        "story",
        "Environment",
        refinement._ENVIRONMENT_STEPS,
    )


def test_environment_legacy_dropdown_and_duplicate_story_are_suppressed() -> None:
    calls: list[tuple[object, ...]] = []
    app = _app(calls)

    refinement.install(app)
    with app.st.expander("How the Environment surface works"):
        pass
    app.surface_story("Environment", (("Duplicate", "Do not show"),))

    assert calls == []


def test_other_surface_stories_and_expanders_are_unchanged() -> None:
    calls: list[tuple[object, ...]] = []
    app = _app(calls)

    refinement.install(app)
    app.render_app_header("Today")
    app.surface_story("Today", (("Observe", "Current information"),))
    with app.st.expander("Cross-asset market detail", expanded=False):
        pass

    assert calls[0] == ("header", "Today")
    assert calls[1] == (
        "story",
        "Today",
        (("Observe", "Current information"),),
    )
    assert calls[2][0:2] == ("expander", "Cross-asset market detail")


def test_install_is_idempotent() -> None:
    calls: list[tuple[object, ...]] = []
    app = _app(calls)

    refinement.install(app)
    first_header = app.render_app_header
    first_story = app.surface_story
    first_expander = app.st.expander
    refinement.install(app)

    assert app.render_app_header is first_header
    assert app.surface_story is first_story
    assert app.st.expander is first_expander


def test_local_and_render_entrypoints_install_after_surface_content() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import environment_story_placement_refinement" in source
        assert source.index("surface_content_refinement.install(app_impl)") < source.index(
            "environment_story_placement_refinement.install(app_impl)"
        )
