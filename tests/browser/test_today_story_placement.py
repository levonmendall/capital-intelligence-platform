from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_today_is_a_ranked_responsive_investor_briefing(
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

        hero = page.locator(".ci-today")
        hero.wait_for(state="visible")
        page.get_by_text("What is moving the investment conversation", exact=True).wait_for()
        page.get_by_text("Research radar", exact=True).first.wait_for()

        assert page.locator(".story-today.process-lens-grid").count() == 0
        assert page.get_by_text("How the Today surface works", exact=True).count() == 0
        assert page.get_by_text("CIO RESPONSE", exact=False).count() == 0
        assert page.get_by_text("PORTFOLIO EFFECT", exact=False).count() == 0

        layout = page.evaluate(
            """() => {
                const hero = document.querySelector('.ci-today').getBoundingClientRect();
                const grids = Array.from(document.querySelectorAll(
                    '.ci-three,.ci-story-grid,.ci-pair,.ci-radar'
                )).map(element => {
                    const box = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return {
                        display: style.display,
                        columns: style.gridTemplateColumns,
                        left: box.left,
                        right: box.right,
                        scrollWidth: element.scrollWidth,
                        clientWidth: element.clientWidth
                    };
                });
                return {
                    viewportWidth: window.innerWidth,
                    documentWidth: document.documentElement.scrollWidth,
                    heroLeft: hero.left,
                    heroRight: hero.right,
                    grids
                };
            }"""
        )
        assert layout["documentWidth"] <= layout["viewportWidth"] + 2
        assert layout["heroLeft"] >= -1
        assert layout["heroRight"] <= layout["viewportWidth"] + 1
        assert all(grid["display"] == "grid" for grid in layout["grids"])
        assert all(grid["scrollWidth"] <= grid["clientWidth"] + 2 for grid in layout["grids"])

        if viewport_name == "iphone":
            assert all(
                len([value for value in grid["columns"].split(" ") if value]) == 1
                for grid in layout["grids"]
            )
        browser.close()
