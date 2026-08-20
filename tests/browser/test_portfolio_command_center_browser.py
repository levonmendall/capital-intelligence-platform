from __future__ import annotations

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

pytestmark = pytest.mark.skipif(
    os.getenv("CAPITAL_INTELLIGENCE_BROWSER_TESTS") != "1",
    reason="real browser gate is opt-in outside CI",
)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def portfolio_command_center(tmp_path_factory):
    root = tmp_path_factory.mktemp("portfolio-command-center-browser")
    ensure_canonical_portfolio_store(root / "canonical_portfolio.db")
    port = _port()
    environment = os.environ.copy()
    environment.update(
        {
            "RENDER": "true",
            "RENDER_EXTERNAL_HOSTNAME": "capital-intelligence.test",
            "CAPITAL_INTELLIGENCE_PORTFOLIO_ONLY_UI": "true",
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
            "CAPITAL_INTELLIGENCE_RELEASE": "portfolio-command-center-browser",
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
            raise AssertionError(f"Streamlit exited before Portfolio Command Center test:\n{output}")
        try:
            with urllib.request.urlopen(health, timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        process.terminate()
        raise AssertionError("Portfolio Command Center did not become healthy within 30 seconds")

    yield f"http://127.0.0.1:{port}"

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _assert_command_center(page) -> dict[str, object]:
    page.get_by_text("Portfolio Command Center", exact=True).wait_for(
        state="visible", timeout=15_000
    )
    for label in (
        "PAPER · $250K GENESIS",
        "AUTO PAPER EXECUTION · ON",
        "LIVE MONEY · DISABLED",
        "Current portfolio NAV",
        "Evidence accumulation",
        "Read-only progress · thresholds unchanged",
        "Governed classes",
        "Reached now",
        "Equity curve",
        "P&L attribution",
        "Open paper positions",
        "Recent paper trades",
        "Skipped / rejected allocations",
        "Decision pipeline status",
        "What needs attention next",
    ):
        page.get_by_text(label, exact=True).first.wait_for(state="visible", timeout=15_000)

    for asset_class in (
        "U.S. equities",
        "U.S. ETFs",
        "Cash equivalents",
        "Fixed income",
        "International equities",
        "Commodities",
        "FX",
        "Crypto",
        "Real estate",
        "Futures",
        "Options",
        "Volatility",
        "Alternatives",
    ):
        page.get_by_text(asset_class, exact=True).first.wait_for(state="visible", timeout=15_000)

    assert page.locator(".cie-command-center .metrics .metric").count() == 8
    assert page.locator(".cie-command-center .asset-evidence-card").count() == 13
    assert page.get_by_text("Asset class evaluation status", exact=True).count() == 0
    assert page.get_by_text("Today", exact=True).count() == 0
    assert page.get_by_text("Environment", exact=True).count() == 0
    assert page.get_by_text("History", exact=True).count() == 0

    layout = page.evaluate(
        """() => ({
          horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
          sidebarVisible: (() => {
            const el = document.querySelector('[data-testid="stSidebar"]');
            return Boolean(el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 1);
          })(),
          headerVisible: (() => {
            const el = document.querySelector('[data-testid="stHeader"]');
            return Boolean(el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().height > 1);
          })(),
          metricColumns: getComputedStyle(document.querySelector('.cie-command-center .metrics')).gridTemplateColumns.split(' ').length,
          evidenceSummaryColumns: getComputedStyle(document.querySelector('.cie-command-center .evidence-summary-grid')).gridTemplateColumns.split(' ').length,
          evidenceMetricColumns: getComputedStyle(document.querySelector('.cie-command-center .asset-evidence-metrics')).gridTemplateColumns.split(' ').length,
          visibleMobileLists: [...document.querySelectorAll('.cie-command-center .mobile-list')].filter(el => getComputedStyle(el).display !== 'none').length,
          visibleTables: [...document.querySelectorAll('.cie-command-center .table-wrap')].filter(el => getComputedStyle(el).display !== 'none').length,
        })"""
    )
    assert layout["horizontalOverflow"] <= 1
    assert layout["sidebarVisible"] is False
    assert layout["headerVisible"] is False
    return layout


@pytest.mark.parametrize(
    ("name", "viewport"),
    (
        ("desktop", {"width": 1440, "height": 1000}),
        ("iphone", {"width": 390, "height": 844}),
    ),
)
def test_production_portfolio_command_center_real_browser(
    portfolio_command_center,
    name,
    viewport,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    chrome = os.environ.get("CAPITAL_INTELLIGENCE_SYSTEM_CHROME", "").strip()
    report_directory = ROOT / "reports" / "browser"
    report_directory.mkdir(parents=True, exist_ok=True)

    launch_kwargs = {"headless": True}
    if chrome:
        launch_kwargs["executable_path"] = chrome

    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport=viewport, device_scale_factor=1)
        page.goto(portfolio_command_center, wait_until="networkidle")
        layout = _assert_command_center(page)

        if name == "iphone":
            assert layout["metricColumns"] == 2
            assert layout["evidenceSummaryColumns"] == 2
            assert layout["evidenceMetricColumns"] == 2
            assert layout["visibleMobileLists"] >= 2
            assert layout["visibleTables"] == 0
        else:
            assert layout["metricColumns"] == 8
            assert layout["evidenceSummaryColumns"] == 3
            assert layout["evidenceMetricColumns"] == 6
            assert layout["visibleTables"] >= 2

        page.screenshot(
            path=str(report_directory / f"portfolio-command-center-{name}.png"),
            full_page=True,
        )
        browser.close()
