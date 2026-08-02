from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


def _layout(locator):
    return locator.evaluate(
        """element => {
            const style = getComputedStyle(element);
            const parent = element.getBoundingClientRect();
            const children = Array.from(element.children).map(child => {
                const box = child.getBoundingClientRect();
                return {left: box.left, right: box.right, top: box.top, width: box.width};
            });
            return {
                display: style.display,
                columns: style.gridTemplateColumns,
                overflowX: style.overflowX,
                scrollWidth: element.scrollWidth,
                clientWidth: element.clientWidth,
                left: parent.left,
                right: parent.right,
                children
            };
        }"""
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

        editorial = page.locator(".today-editorial")
        radar = page.locator(".research-radar")
        editorial.wait_for(state="visible")
        radar.wait_for(state="visible")

        editorial_box = editorial.bounding_box()
        radar_box = radar.bounding_box()
        assert editorial_box is not None
        assert radar_box is not None
        assert editorial_box["y"] < radar_box["y"]

        assert page.locator(".process-lens-grid").count() == 0
        assert page.get_by_text(
            "What is moving the investment conversation", exact=True
        ).count() == 1
        assert page.get_by_text(
            "What the opportunity process is finding", exact=True
        ).count() == 1
        assert page.get_by_text("CIO response", exact=False).count() == 0
        assert page.get_by_text("Portfolio effect", exact=False).count() == 0
        assert page.get_by_text("Portfolio value", exact=True).count() == 0
        assert page.get_by_text("Available cash", exact=True).count() == 0

        grids = page.locator(
            ".story-explanation-grid, .today-secondary-grid, "
            ".today-watch-panel, .radar-grid"
        )
        for index in range(grids.count()):
            layout = _layout(grids.nth(index))
            assert layout["overflowX"] != "auto"
            assert layout["scrollWidth"] <= layout["clientWidth"] + 2
            assert all(
                child["left"] >= layout["left"] - 1
                and child["right"] <= layout["right"] + 1
                for child in layout["children"]
            )

        explanation = page.locator(".story-explanation-grid")
        if explanation.count():
            layout = _layout(explanation.first)
            column_count = len([value for value in layout["columns"].split(" ") if value])
            if viewport_name == "iphone":
                assert column_count == 1
            else:
                assert column_count == 3

        document_width = page.evaluate(
            """() => ({
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth
            })"""
        )
        assert document_width["scrollWidth"] <= document_width["clientWidth"] + 2
        browser.close()
