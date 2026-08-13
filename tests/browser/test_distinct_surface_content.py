from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.browser.test_streamlit_browser import BASELINE, live_streamlit


ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


def _assert_hidden_or_absent(locator) -> None:
    """Allow Streamlit to retain stale surface fragment DOM only if hidden."""

    assert locator.count() <= 1
    if locator.count() == 1:
        locator.first.wait_for(state="hidden")


def test_render_entrypoint_preserves_portfolio_refinement_contract() -> None:
    """Keep Render on the same final Portfolio renderer as the canonical UI."""

    source = (ROOT / "render_app.py").read_text(encoding="utf-8")
    assert "import portfolio_ui_refinement" in source
    assert "portfolio_first_ui_refinement" not in source
    assert "_portfolio_first_sync_renderer" not in source

    main_source = source[source.index("def main() -> None:") :]
    install_call = "portfolio_ui_refinement.install(app_impl)"
    prepare_call = "prepare_render_surface_runtime()"
    create_call = "create_streamlit_application("
    assert install_call in main_source
    assert main_source.index(install_call) < main_source.index(prepare_call)
    assert main_source.index(prepare_call) < main_source.index(create_call)

    runtime_source = source[
        source.index("def prepare_render_surface_runtime() -> None:") :
        source.index("def deployment_context_from_environment()")
    ]
    assert "portfolio_first_ui_refinement" not in runtime_source
    assert "_portfolio_first_sync_renderer" not in runtime_source


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
        assert page.get_by_text("Performance vs benchmarks", exact=True).count() == 0
        assert page.get_by_text("Detailed decision trail", exact=True).count() == 0

        navigation.get_by_role("radio", name="Environment", exact=True).click()
        page.get_by_text("Current environment", exact=True).wait_for()
        page.get_by_text("Four macro drivers", exact=True).wait_for()
        page.get_by_text("How this backdrop reaches markets", exact=True).wait_for()
        assert page.get_by_text("Market state", exact=True).count() == 0
        assert page.get_by_text("CIO / research funnel", exact=True).count() == 0
        assert page.get_by_text("Current holdings", exact=True).count() == 0
        assert page.get_by_text("Performance vs benchmarks", exact=True).count() == 0
        assert page.get_by_text("Detailed decision trail", exact=True).count() == 0

        navigation.get_by_role("radio", name="Portfolio", exact=True).click()
        page.get_by_text("LATEST CIO POSITIONING", exact=True).first.wait_for()
        page.get_by_text("Performance vs benchmarks", exact=True).first.wait_for()
        page.get_by_text("Current → target allocation", exact=True).first.wait_for()
        page.get_by_text("Current holdings", exact=True).first.wait_for()
        page.get_by_text("Performance attribution", exact=True).first.wait_for()
        page.get_by_text("Risk & exposure", exact=True).first.wait_for()
        page.get_by_text("Pending implementation", exact=True).first.wait_for()
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
        _assert_hidden_or_absent(
            page.get_by_text("Current holdings", exact=True)
        )
        assert page.get_by_text("Performance vs benchmarks", exact=True).count() == 0
        browser.close()
