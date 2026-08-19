from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def use_preinstalled_chrome(monkeypatch):
    """Route Playwright Chromium launches to CI's preinstalled Chrome when supplied."""

    chrome = os.getenv("CAPITAL_INTELLIGENCE_SYSTEM_CHROME", "").strip()
    if not chrome:
        return

    playwright = pytest.importorskip("playwright.sync_api")
    original_launch = playwright.BrowserType.launch

    def launch(browser_type, *args, **kwargs):
        if getattr(browser_type, "name", "") == "chromium":
            kwargs.setdefault("executable_path", chrome)
        return original_launch(browser_type, *args, **kwargs)

    monkeypatch.setattr(playwright.BrowserType, "launch", launch)
