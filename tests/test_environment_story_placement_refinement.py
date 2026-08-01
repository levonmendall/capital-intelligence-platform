from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import environment_story_placement_refinement as refinement


class _FakeStreamlit:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls

    def html(self, value: str) -> None:
        self.calls.append(("html", value))

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


def test_environment_story_matches_today_two_by_two_mobile_grid() -> None:
    calls: list[tuple[object, ...]] = []
    app = _app(calls)

    refinement.install(app)
    app.render_app_header("Environment")

    assert calls[0] == ("header", "Environment")
    assert calls[1][0] == "html"
    markup = str(calls[1][1])
    assert (
        'class="surface-story story-environment process-lens-grid '
        'process-lens-environment"'
    ) in markup
    assert 'class="process-lens-cards"' in markup
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in markup
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in markup
    assert "aspect-ratio: 1 / 1" in markup
    assert "overflow-x: auto" not in markup
    assert markup.count('class="process-lens-card"') == 4
    for label in ("Measure", "Classify", "Confirm", "Monitor"):
        assert f'class="process-lens-card-title">{label}</div>' in markup


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
