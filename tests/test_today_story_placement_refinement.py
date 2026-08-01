from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import today_story_placement_refinement as refinement


class _FakeStreamlit:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

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


def test_today_story_is_visible_immediately_after_surface_header() -> None:
    events: list[tuple[object, ...]] = []
    app_impl = _application(events)

    refinement.install(app_impl)
    app_impl.render_app_header("Today")

    assert events[0] == ("header", "Today")
    assert events[1][0:2] == ("story", "Today")
    assert [step[0] for step in events[1][2]] == [
        "Observe",
        "Explain",
        "Resolve",
        "Act",
    ]


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


def test_install_is_idempotent_and_active_in_both_entrypoints() -> None:
    events: list[tuple[object, ...]] = []
    app_impl = _application(events)

    refinement.install(app_impl)
    first_header = app_impl.render_app_header
    refinement.install(app_impl)

    assert app_impl.render_app_header is first_header
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import today_story_placement_refinement" in source
        assert "today_story_placement_refinement.install(app_impl)" in source
