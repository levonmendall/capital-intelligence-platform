from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_portfolio_links_to_a_dedicated_full_cio_report(
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
        navigation.get_by_role("radio", name="Portfolio", exact=True).click()

        capital = page.get_by_text("Capital structure", exact=True).first
        report_link = page.get_by_role("link", name="View full CIO report", exact=True)
        capital.wait_for(state="visible", timeout=15_000)
        report_link.wait_for(state="visible", timeout=15_000)
        assert page.get_by_text("Monitoring and reversal conditions", exact=True).count() == 0
        assert page.get_by_text("Decision lineage", exact=True).count() == 0

        capital_box = capital.bounding_box()
        link_box = report_link.bounding_box()
        assert capital_box is not None
        assert link_box is not None
        assert capital_box["y"] < link_box["y"]

        report_link.click()
        page.get_by_text("Full CIO report", exact=True).first.wait_for(
            state="visible",
            timeout=15_000,
        )
        page.get_by_text("Decision context", exact=True).wait_for()
        page.get_by_text("Monitoring and reversal conditions", exact=True).wait_for()
        page.get_by_text("Decision lineage", exact=True).wait_for()
        assert page.get_by_text("Capital structure", exact=True).count() == 0
        assert page.get_by_role("link", name="View full CIO report", exact=True).count() == 0

        back = page.get_by_role("link", name="Back to Portfolio", exact=True)
        back.wait_for(state="visible")
        back.click()
        page.get_by_text("Capital structure", exact=True).first.wait_for(
            state="visible",
            timeout=15_000,
        )
        page.get_by_role("link", name="View full CIO report", exact=True).wait_for()
        assert page.get_by_text("Full CIO report", exact=True).count() == 0
        browser.close()
