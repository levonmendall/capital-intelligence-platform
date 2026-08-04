from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_portfolio_opens_full_cio_report_without_replacing_authenticated_session(
    live_streamlit,
    viewport_name,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    viewport = BASELINE["viewports"][viewport_name]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport, device_scale_factor=1)
        page.goto(live_streamlit, wait_until="networkidle")
        main_frame_navigations: list[str] = []

        def record_navigation(frame) -> None:
            if frame == page.main_frame:
                main_frame_navigations.append(frame.url)

        page.on("framenavigated", record_navigation)
        navigation = page.locator('[data-testid="stButtonGroup"]').get_by_role(
            "radiogroup"
        )
        navigation.wait_for(state="visible")
        navigation.get_by_role("radio", name="Portfolio", exact=True).click()

        capital = page.get_by_text("Capital structure", exact=True).first
        report_button = page.get_by_role(
            "button",
            name="View full CIO report",
            exact=True,
        )
        capital.wait_for(state="visible", timeout=15_000)
        report_button.wait_for(state="visible", timeout=15_000)
        assert page.get_by_text("Monitoring and reversal conditions", exact=True).count() == 0
        assert page.get_by_text("Decision lineage", exact=True).count() == 0

        capital_box = capital.bounding_box()
        button_box = report_button.bounding_box()
        assert capital_box is not None
        assert button_box is not None
        assert capital_box["y"] < button_box["y"]

        report_button.click()
        page.get_by_text("Full CIO report", exact=True).first.wait_for(
            state="visible",
            timeout=15_000,
        )
        page.get_by_text("Decision context", exact=True).wait_for()
        page.get_by_text("Monitoring and reversal conditions", exact=True).wait_for()
        page.get_by_text("Decision lineage", exact=True).wait_for()
        assert "view=cio-report" in page.url
        assert main_frame_navigations == []
        assert page.get_by_text("Capital structure", exact=True).count() == 0
        assert page.get_by_role(
            "button",
            name="View full CIO report",
            exact=True,
        ).count() == 0
        assert page.get_by_label("Email address").count() == 0

        back = page.get_by_role("button", name="Back to Portfolio", exact=False)
        back.wait_for(state="visible")
        back.click()
        page.get_by_text("Capital structure", exact=True).first.wait_for(
            state="visible",
            timeout=15_000,
        )
        page.get_by_role(
            "button",
            name="View full CIO report",
            exact=True,
        ).wait_for()
        assert "view=cio-report" not in page.url
        assert main_frame_navigations == []
        assert page.get_by_text("Full CIO report", exact=True).count() == 0
        assert page.get_by_label("Email address").count() == 0
        browser.close()
