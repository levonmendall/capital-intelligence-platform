from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_environment_story_is_visible_horizontal_and_before_economic_content(
    live_streamlit,
    viewport_name,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    viewport = BASELINE["viewports"][viewport_name]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport, device_scale_factor=1)
        page.goto(live_streamlit, wait_until="networkidle")

        navigation = page.locator('[data-testid="stButtonGroup"]').get_by_role(
            "radiogroup"
        )
        navigation.wait_for(state="visible")
        navigation.get_by_role("radio", name="Environment", exact=True).click()
        page.get_by_role("heading", name="Environment", exact=True).wait_for()

        story = page.locator(".surface-story.story-environment")
        story.wait_for(state="visible")
        economy = page.get_by_text("Economy and investing", exact=True).first
        economy.wait_for(state="visible")

        story_box = story.bounding_box()
        economy_box = economy.bounding_box()
        assert story_box is not None
        assert economy_box is not None
        assert story_box["y"] < economy_box["y"]
        assert (
            page.get_by_text("How the Environment surface works", exact=True).count()
            == 0
        )

        for label in ("Measure", "Classify", "Confirm", "Monitor"):
            assert story.get_by_text(label, exact=True).count() == 1

        layout = story.evaluate(
            """element => {
                const style = getComputedStyle(element);
                const steps = Array.from(element.querySelectorAll('.story-step'));
                const boxes = steps.map((step) => step.getBoundingClientRect());
                return {
                    overflowX: style.overflowX,
                    scrollWidth: element.scrollWidth,
                    clientWidth: element.clientWidth,
                    lefts: boxes.map((box) => box.left),
                    tops: boxes.map((box) => box.top),
                };
            }"""
        )
        assert layout["overflowX"] in {"auto", "scroll"}
        assert len(layout["lefts"]) == 4
        assert layout["lefts"] == sorted(layout["lefts"])
        assert max(layout["tops"]) - min(layout["tops"]) <= 3
        if viewport_name == "iphone":
            assert layout["scrollWidth"] > layout["clientWidth"]
        browser.close()
