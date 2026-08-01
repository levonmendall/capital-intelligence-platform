from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_today_story_is_visible_before_investment_world_section(
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
        navigation.get_by_role("radio", name="Today", exact=True).click()
        page.get_by_role("heading", name="Today", exact=True).wait_for()

        story = page.locator(".surface-story.story-today")
        story.wait_for(state="visible")
        investment_world = page.get_by_text("Investment world today", exact=True).first
        investment_world.wait_for(state="visible")

        story_box = story.bounding_box()
        investment_box = investment_world.bounding_box()
        assert story_box is not None
        assert investment_box is not None
        assert story_box["y"] < investment_box["y"]
        assert page.get_by_text("How the Today surface works", exact=True).count() == 0

        for label in ("Observe", "Explain", "Resolve", "Act"):
            assert story.get_by_text(label, exact=True).count() == 1
        browser.close()
