from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from portfolio.state import ensure_canonical_portfolio_store


ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads(
    (ROOT / "tests" / "visual_baselines" / "streamlit-layout-v1.json").read_text(
        encoding="utf-8"
    )
)
SURFACE_BODY_TEXT = {
    "Today": "Investment world today",
    "Environment": "Economy and investing",
    "Portfolio": "Portfolio posture",
    "History": "Outcome status",
}

pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def live_streamlit(tmp_path_factory):
    root = tmp_path_factory.mktemp("streamlit-browser")
    ensure_canonical_portfolio_store(root / "canonical_portfolio.db")
    port = _port()
    environment = os.environ.copy()
    environment.update(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(root),
            "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE": str(root / "canonical_portfolio.db"),
            "CAPITAL_INTELLIGENCE_JOURNAL_DATABASE": str(root / "journal.db"),
            "CAPITAL_INTELLIGENCE_IDENTITY_DATABASE": str(root / "identity.db"),
            "CAPITAL_INTELLIGENCE_ALERT_DATABASE": str(root / "alerts.db"),
            "CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE": str(root / "snapshots.db"),
            "CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED": "false",
            "CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL": "false",
            "CAPITAL_INTELLIGENCE_REQUIRE_CANONICAL_ENVIRONMENT": "false",
            "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED": "false",
            "CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE": "disabled",
            "CAPITAL_INTELLIGENCE_RELEASE": "browser-render-entrypoint",
            "RENDER_EXTERNAL_HOSTNAME": "capital-intelligence.test",
        }
    )
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "render_app.py",
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ),
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    health = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = "" if process.stdout is None else process.stdout.read()
            raise AssertionError(f"Streamlit exited before browser test:\n{output}")
        try:
            with urllib.request.urlopen(health, timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        process.terminate()
        raise AssertionError("Streamlit did not become healthy within 30 seconds")
    yield f"http://127.0.0.1:{port}"
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _assert_public_boundary(page) -> None:
    page.get_by_text(BASELINE["required_public_text"], exact=True).wait_for()
    for label in BASELINE["prohibited_public_controls"]:
        assert page.get_by_text(label, exact=True).count() == 0


def _assert_surface_body(page, surface: str) -> None:
    page.get_by_text(SURFACE_BODY_TEXT[surface], exact=True).first.wait_for(
        state="visible",
        timeout=15_000,
    )


def _layout_snapshot(page) -> dict[str, object]:
    return page.evaluate(
        """() => {
          const buttons = [...document.querySelectorAll('[data-testid="stButtonGroup"] button')];
          const heights = buttons.map((button) => button.getBoundingClientRect().height);
          return {
            navigationCount: buttons.length,
            minimumNavigationHeight: heights.length ? Math.min(...heights) : 0,
            horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
            headingVisible: Boolean(document.querySelector('.compact-surface-head h1')),
            sectionHeaderCount: document.querySelectorAll('.section-header').length,
            statusRowCount: document.querySelectorAll('.status-row').length,
          };
        }"""
    )


@pytest.mark.parametrize("viewport_name", ("desktop", "iphone"))
def test_public_four_screen_browser_and_visual_contract(live_streamlit, viewport_name) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    viewport = BASELINE["viewports"][viewport_name]
    report_directory = ROOT / "reports" / "browser"
    report_directory.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport, device_scale_factor=1)
        page.goto(live_streamlit, wait_until="networkidle")
        _assert_public_boundary(page)
        navigation = page.locator('[data-testid="stButtonGroup"]').get_by_role(
            "radiogroup"
        )
        navigation.wait_for(state="visible")
        assert navigation.count() == 1
        for surface in ("Today", "Environment", "Portfolio", "History"):
            navigation.get_by_role("radio", name=surface, exact=True).click()
            page.get_by_role("heading", name=surface, exact=True).wait_for()
            _assert_surface_body(page, surface)
            _assert_public_boundary(page)
        layout = _layout_snapshot(page)
        assert layout["navigationCount"] == BASELINE["primary_surface_count"]
        assert layout["horizontalOverflow"] <= BASELINE["maximum_horizontal_overflow_pixels"]
        assert layout["headingVisible"] is True
        assert layout["sectionHeaderCount"] >= 1 or layout["statusRowCount"] >= 1
        if viewport_name == "iphone":
            assert layout["minimumNavigationHeight"] >= BASELINE["minimum_mobile_navigation_height_pixels"]
        page.screenshot(path=report_directory / f"streamlit-{viewport_name}.png", full_page=True)
        (report_directory / f"streamlit-{viewport_name}-layout.json").write_text(
            json.dumps(layout, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        browser.close()
