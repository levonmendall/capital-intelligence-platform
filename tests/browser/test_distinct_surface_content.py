from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


def _assert_hidden_or_absent(locator) -> None:
    """Allow Streamlit to retain stale Environment fragment DOM only if hidden."""

    assert locator.count() <= 1
    if locator.count() == 1:
        assert locator.first.is_visible() is False


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_primary_surfaces_have_distinct_information_ownership(
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
        page.get_by_text("Market state", exact=True).wait_for()
        page.get_by_text("CIO / research funnel", exact=True).wait_for()
        assert page.get_by_text("How this backdrop reaches markets", exact=True).count() == 0
        assert page.get_by_text("Current holdings", exact=True).count() == 0
        assert page.get_by_text("CIO decision", exact=True).count() == 0
        assert page.get_by_text("Detailed decision trail", exact=True).count() == 0

        navigation.get_by_role("radio", name="Environment", exact=True).click()
        page.get_by_text("Current environment", exact=True).wait_for()
        page.get_by_text("Four macro drivers", exact=True).wait_for()
        page.get_by_text("How this backdrop reaches markets", exact=True).wait_for()
        assert page.get_by_text("Market state", exact=True).count() == 0
        assert page.get_by_text("CIO / research funnel", exact=True).count() == 0
        assert page.get_by_text("Current holdings", exact=True).count() == 0
        assert page.get_by_text("CIO decision", exact=True).count() == 0
        assert page.get_by_text("Detailed decision trail", exact=True).count() == 0

        navigation.get_by_role("radio", name="Portfolio", exact=True).click()
        page.get_by_text("Current holdings", exact=True).first.wait_for()
        page.get_by_text("CIO decision", exact=True).first.wait_for()
        page.get_by_text("Capital deployment", exact=True).first.wait_for()
        page.get_by_text("Outstanding portfolio actions", exact=True).first.wait_for()
        assert page.get_by_text("Market state", exact=True).count() == 0
        _assert_hidden_or_absent(
            page.get_by_text("How this backdrop reaches markets", exact=True)
        )
        assert page.get_by_text("Detailed decision trail", exact=True).count() == 0

        navigation.get_by_role("radio", name="History", exact=True).click()
        page.get_by_text("Detailed decision trail", exact=True).wait_for()
        assert page.get_by_text("Market state", exact=True).count() == 0
        _assert_hidden_or_absent(
            page.get_by_text("How this backdrop reaches markets", exact=True)
        )
        assert page.get_by_text("Current holdings", exact=True).count() == 0
        assert page.get_by_text("CIO decision", exact=True).count() == 0
        browser.close()
