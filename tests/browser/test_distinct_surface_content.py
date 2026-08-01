from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_primary_surfaces_do_not_repeat_each_others_core_content(
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
        page.get_by_text("Today's investment developments", exact=True).wait_for()
        page.get_by_text("ASSETS IN FOCUS", exact=False).first.wait_for()
        page.get_by_text("TRANSMISSION CHANNELS", exact=False).first.wait_for()
        assert page.get_by_text("CIO RESPONSE", exact=False).count() == 0
        assert page.get_by_text("PORTFOLIO EFFECT", exact=False).count() == 0
        assert page.get_by_text("Economic and market backdrop", exact=True).count() == 0
        assert page.get_by_text("Portfolio posture", exact=True).count() == 0

        navigation.get_by_role("radio", name="Environment", exact=True).click()
        page.get_by_text("Economic and market backdrop", exact=True).wait_for()
        page.get_by_text("ECONOMIC STATE", exact=False).first.wait_for()
        page.get_by_text("ASSET-CLASS SENSITIVITY", exact=False).first.wait_for()
        assert page.get_by_text("CIO RESPONSE", exact=False).count() == 0
        assert page.get_by_text("PORTFOLIO EFFECT", exact=False).count() == 0
        assert page.get_by_text("Today's investment developments", exact=True).count() == 0
        assert page.get_by_text("Portfolio posture", exact=True).count() == 0

        navigation.get_by_role("radio", name="Portfolio", exact=True).click()
        page.get_by_text("Portfolio posture", exact=True).wait_for()
        assert page.get_by_text("Today's investment developments", exact=True).count() == 0
        assert page.get_by_text("Economic and market backdrop", exact=True).count() == 0
        assert page.get_by_text("Detailed decision trail", exact=True).count() == 0

        navigation.get_by_role("radio", name="History", exact=True).click()
        page.get_by_text("Detailed decision trail", exact=True).wait_for()
        assert page.get_by_text("Today's investment developments", exact=True).count() == 0
        assert page.get_by_text("Economic and market backdrop", exact=True).count() == 0
        assert page.get_by_text("Portfolio posture", exact=True).count() == 0
        browser.close()
