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


def _scroll_and_measure_navigation(page) -> dict[str, object]:
    return page.evaluate(
        """async () => {
          const row = document.querySelector(
            'div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark)'
          );
          const wrapper = row ? row.parentElement : null;
          if (!row || !wrapper) {
            return {
              wrapperFound: false,
              position: '',
              top: 999,
              bottom: -999,
              navigationVisible: false,
              scrollDistance: 0,
            };
          }

          const main = document.querySelector('[data-testid="stMain"]');
          const documentScroller = document.scrollingElement || document.documentElement;
          const scrollTarget =
            main && main.scrollHeight - main.clientHeight > 100
              ? main
              : documentScroller;
          const before = Number(scrollTarget.scrollTop || window.scrollY || 0);
          if (scrollTarget === documentScroller) {
            window.scrollTo(0, documentScroller.scrollHeight);
          } else {
            scrollTarget.scrollTop = scrollTarget.scrollHeight;
          }
          await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

          const rect = wrapper.getBoundingClientRect();
          const after = Number(scrollTarget.scrollTop || window.scrollY || 0);
          const style = getComputedStyle(wrapper);
          return {
            wrapperFound: true,
            position: style.position,
            top: rect.top,
            bottom: rect.bottom,
            navigationVisible:
              style.display !== 'none' &&
              style.visibility !== 'hidden' &&
              rect.bottom > 0 &&
              rect.top < window.innerHeight,
            scrollDistance: Math.max(0, after - before),
          };
        }"""
    )


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_primary_navigation_remains_pinned_after_page_scroll(
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
        navigation.get_by_role("radio", name="History", exact=True).click()
        page.get_by_role("heading", name="History", exact=True).wait_for()
        page.get_by_text("Detailed decision trail", exact=True).wait_for()

        measurement = _scroll_and_measure_navigation(page)

        assert measurement["wrapperFound"] is True
        assert measurement["position"] == "sticky"
        assert measurement["scrollDistance"] > 100
        assert -1 <= measurement["top"] <= 96
        assert measurement["bottom"] > 0
        assert measurement["navigationVisible"] is True
        browser.close()
