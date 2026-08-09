from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_today_is_a_compact_responsive_investor_briefing(
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

        page.get_by_text("Market state", exact=True).wait_for()
        page.get_by_text("Briefing health", exact=True).wait_for()
        page.get_by_text("CIO / research funnel", exact=True).wait_for()
        page.get_by_text("What to watch next", exact=True).wait_for()
        page.get_by_text("U.S. listed session", exact=False).wait_for()
        page.get_by_text("direct spot crypto trades 24/7", exact=False).wait_for()

        assert page.locator(".ci-trust-strip").count() == 1
        assert page.locator(".ci-funnel").count() == 1
        assert page.get_by_text("Research radar", exact=True).count() == 0
        assert page.get_by_text("What is moving the investment conversation", exact=True).count() == 0
        assert page.get_by_text("How the Today surface works", exact=True).count() == 0

        explanation = page.get_by_text("Why these developments matter", exact=True)
        sources = page.get_by_text("Sources and timing", exact=True)
        explanation.wait_for()
        sources.wait_for()
        assert page.locator('[data-testid="stExpander"]').filter(
            has_text="Why these developments matter"
        ).locator('[data-testid="stExpanderDetails"]').is_hidden()
        assert page.locator('[data-testid="stExpander"]').filter(
            has_text="Sources and timing"
        ).locator('[data-testid="stExpanderDetails"]').is_hidden()

        layout = page.evaluate(
            """() => {
                const selectors = [
                    '.ci-trust-strip',
                    '.ci-development-list',
                    '.ci-impact',
                    '.ci-funnel',
                    '.ci-watch-compact'
                ];
                const regions = selectors.flatMap(selector =>
                    Array.from(document.querySelectorAll(selector)).map(element => {
                        const box = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return {
                            selector,
                            display: style.display,
                            columns: style.gridTemplateColumns,
                            left: box.left,
                            right: box.right,
                            scrollWidth: element.scrollWidth,
                            clientWidth: element.clientWidth
                        };
                    })
                );
                const nav = document.querySelector(
                    'div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark)'
                );
                const navBox = nav ? nav.getBoundingClientRect() : null;
                const brand = nav ? nav.querySelector('.nav-brand-mark') : null;
                const brandBox = brand ? brand.getBoundingClientRect() : null;
                return {
                    viewportWidth: window.innerWidth,
                    documentWidth: document.documentElement.scrollWidth,
                    regions,
                    navHeight: navBox ? navBox.height : null,
                    brandVisible: Boolean(
                        brand &&
                        brand.getClientRects().length > 0 &&
                        brandBox &&
                        brandBox.width > 1 &&
                        brandBox.height > 1 &&
                        getComputedStyle(brand).visibility !== 'hidden'
                    )
                };
            }"""
        )
        assert layout["documentWidth"] <= layout["viewportWidth"] + 2
        assert layout["regions"]
        assert all(region["display"] == "grid" for region in layout["regions"])
        assert all(region["left"] >= -1 for region in layout["regions"])
        assert all(
            region["right"] <= layout["viewportWidth"] + 1
            for region in layout["regions"]
        )
        assert all(
            region["scrollWidth"] <= region["clientWidth"] + 2
            for region in layout["regions"]
        )

        if viewport_name == "iphone":
            assert layout["navHeight"] is not None
            assert layout["navHeight"] < 52
            assert layout["brandVisible"] is False
        browser.close()