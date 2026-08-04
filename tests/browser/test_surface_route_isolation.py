from __future__ import annotations

import os

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_environment_driver_grid_never_survives_on_another_surface(
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

        environment = navigation.get_by_role(
            "radio",
            name="Environment",
            exact=True,
        )
        environment.click()
        page.get_by_text("How this backdrop reaches markets", exact=True).wait_for()
        page.locator(".ci-driver-grid").wait_for(state="visible")
        assert page.get_by_text(
            "Unemployment rate · inverse growth signal",
            exact=True,
        ).count() == 1

        for surface, expected in (
            ("Today", "What is moving the investment conversation"),
            ("Portfolio", "Capital structure"),
            ("History", "Detailed decision trail"),
        ):
            control = navigation.get_by_role("radio", name=surface, exact=True)
            control.click()
            page.get_by_text(expected, exact=True).first.wait_for(state="visible")
            page.wait_for_timeout(1_500)
            assert control.get_attribute("aria-checked") == "true" or (
                control.get_attribute("aria-pressed") == "true"
            )
            assert page.locator(".ci-driver-grid").count() == 0
            assert page.get_by_text(
                "Unemployment rate · inverse growth signal",
                exact=True,
            ).count() == 0
            assert page.get_by_text(
                "How this backdrop reaches markets",
                exact=True,
            ).count() == 0

        browser.close()
