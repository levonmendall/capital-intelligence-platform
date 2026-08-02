from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import today_story_placement_refinement as refinement


class _FakeStreamlit:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    def html(self, value: str) -> None:
        self.events.append(("html", value))

    @contextmanager
    def expander(self, label: str, *args: object, **kwargs: object):
        self.events.append(("expander", label, args, kwargs))
        yield


def _application(events: list[tuple[object, ...]]) -> SimpleNamespace:
    def render_app_header(active_page: str) -> None:
        events.append(("header", active_page))

    def surface_story(active_page: str, steps) -> None:
        events.append(("story", active_page, tuple(steps)))

    return SimpleNamespace(
        render_app_header=render_app_header,
        surface_story=surface_story,
        st=_FakeStreamlit(events),
    )


def test_today_story_is_visible_in_shared_two_by_two_mobile_grid() -> None:
    """The retired module remains independently testable but is not runtime-installed."""

    events: list[tuple[object, ...]] = []
    app_impl = _application(events)

    refinement.install(app_impl)
    app_impl.render_app_header("Today")

    assert events[0] == ("header", "Today")
    assert events[1][0] == "html"
    markup = str(events[1][1])
    assert 'class="surface-story story-today process-lens-grid process-lens-today"' in markup
    assert 'class="process-lens-cards"' in markup
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in markup
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in markup
    assert "aspect-ratio: 1 / 1" in markup
    assert "overflow-x: auto" not in markup
    assert markup.count('class="process-lens-card"') == 4
    for label in ("Observe", "Explain", "Resolve", "Act"):
        assert f'class="process-lens-card-title">{label}</div>' in markup


def test_legacy_today_dropdown_and_duplicate_story_are_suppressed() -> None:
    events: list[tuple[object, ...]] = []
    app_impl = _application(events)

    refinement.install(app_impl)
    with app_impl.st.expander("How the Today surface works", expanded=False):
        app_impl.surface_story(
            "Today",
            (("Observe", "Duplicate story must not render."),),
        )

    assert events == []


def test_other_surface_stories_and_expanders_are_unchanged() -> None:
    events: list[tuple[object, ...]] = []
    app_impl = _application(events)

    refinement.install(app_impl)
    app_impl.render_app_header("Environment")
    with app_impl.st.expander("How the Environment surface works", expanded=False):
        app_impl.surface_story(
            "Environment",
            (("Read", "Observe evidence."), ("Translate", "Explain impact.")),
        )

    assert events[0] == ("header", "Environment")
    assert events[1][0:2] == (
        "expander",
        "How the Environment surface works",
    )
    assert events[2][0:2] == ("story", "Environment")


def test_install_is_idempotent_but_legacy_module_is_not_in_active_entrypoints() -> None:
    events: list[tuple[object, ...]] = []
    app_impl = _application(events)

    refinement.install(app_impl)
    first_header = app_impl.render_app_header
    refinement.install(app_impl)

    assert app_impl.render_app_header is first_header
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "today_story_placement_refinement" not in source
        assert "import environment_story_placement_refinement" in source
        assert source.index("surface_content_refinement.install(app_impl)") < source.index(
            "environment_story_placement_refinement.install(app_impl)"
        )
