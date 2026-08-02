from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import (
    BASELINE,
    _assert_public_boundary,
    live_streamlit,
)


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


def _grid_layout(locator):
    return locator.evaluate(
        """element => {
            const style = getComputedStyle(element);
            const parent = element.getBoundingClientRect();
            const children = Array.from(element.children).map(child => {
                const box = child.getBoundingClientRect();
                return {left: box.left, right: box.right, top: box.top, width: box.width};
            });
            return {
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
def test_environment_is_a_responsive_structural_market_dashboard(
    live_streamlit,
    viewport_name,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    viewport = BASELINE["viewports"][viewport_name]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport, device_scale_factor=1)
        page.goto(live_streamlit, wait_until="networkidle")
        _assert_public_boundary(page)

        navigation = page.locator('[data-testid="stButtonGroup"]').get_by_role(
            "radiogroup"
        )
        navigation.wait_for(state="visible")
        navigation.get_by_role("radio", name="Environment", exact=True).click()
        page.get_by_role("heading", name="Environment", exact=True).wait_for()

        dashboard = page.locator(".environment-dashboard")
        drivers = page.locator(".environment-driver-grid")
        market_map = page.locator(".market-map")
        dashboard.wait_for(state="visible")
        drivers.wait_for(state="visible")
        market_map.wait_for(state="visible")

        assert page.locator(".process-lens-grid").count() == 0
        assert page.locator(".environment-driver").count() == 4
        assert page.locator(".market-map-card").count() == 4
        for label in ("Growth", "Inflation", "Rates", "Liquidity"):
            assert page.get_by_text(label, exact=True).count() >= 1
        assert page.get_by_text(
            "How this backdrop reaches markets", exact=True
        ).count() == 1
        assert page.get_by_text(
            "Read the economy through four channels", exact=True
        ).count() == 1
        assert page.get_by_text("CIO response", exact=False).count() == 0
        assert page.get_by_text("Portfolio effect", exact=False).count() == 0
        assert page.get_by_text(
            "What is moving the investment conversation", exact=True
        ).count() == 0
        assert page.locator(".research-radar").count() == 0

        expected_columns = 1 if viewport_name == "iphone" else 4
        for grid in (drivers, market_map):
            layout = _grid_layout(grid)
            columns = [value for value in layout["columns"].split(" ") if value]
            assert len(columns) == expected_columns
            assert layout["overflowX"] != "auto"
            assert layout["scrollWidth"] <= layout["clientWidth"] + 2
            assert all(
                child["left"] >= layout["left"] - 1
                and child["right"] <= layout["right"] + 1
                for child in layout["children"]
            )

        document_width = page.evaluate(
            """() => ({
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth
            })"""
        )
        assert document_width["scrollWidth"] <= document_width["clientWidth"] + 2
        browser.close()
