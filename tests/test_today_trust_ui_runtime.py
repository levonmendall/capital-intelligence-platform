from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import today_trust_ui_runtime as trust


def test_closed_us_session_does_not_imply_crypto_is_closed() -> None:
    label = trust.market_session_summary({"market_open": False})

    assert "U.S. listed session closed" in label
    assert "direct spot crypto trades 24/7" in label
    assert label != "Market closed"


def test_source_timing_separates_check_time_from_publication_time() -> None:
    now = datetime(2026, 8, 9, 15, 0, tzinfo=timezone.utc)
    checked_at = now - timedelta(minutes=15)
    published_at = datetime(2026, 1, 2, 18, 30, tzinfo=timezone.utc)

    label = trust.source_timing_label(
        checked_at,
        published_at,
        now=now,
    )

    assert "Sources checked 15m ago" in label
    assert "observation published Jan 02, 2026 · 18:30 UTC" in label


def test_current_sources_without_new_story_are_not_called_refreshing() -> None:
    now = datetime(2026, 8, 9, 15, 0, tzinfo=timezone.utc)

    label = trust.source_health_summary(
        state="available",
        checked_at=now - timedelta(minutes=10),
        current_count=0,
        retained_count=2,
        now=now,
    )

    assert "Sources current" in label
    assert "no new qualifying developments" in label
    assert "refresh" not in label.lower()


def test_funnel_uses_successive_persisted_cohorts() -> None:
    snapshot = SimpleNamespace(
        broad_assets_screened=1000,
        snapshot_covered=800,
        companies_deepened=120,
        governed_candidates=25,
        opportunities_reaching_cio=4,
    )

    stages = trust.opportunity_funnel_stages(snapshot)

    assert [stage[0] for stage in stages] == [
        "Universe observed",
        "Usable snapshots",
        "Deep analysis",
        "Evidence complete",
        "Reached CIO",
    ]
    assert [stage[1] for stage in stages] == ["1,000", "800", "120", "25", "4"]
    assert not any(stage[3] for stage in stages)


def test_funnel_flags_impossible_downstream_count_instead_of_clamping() -> None:
    snapshot = SimpleNamespace(
        broad_assets_screened=100,
        snapshot_covered=80,
        companies_deepened=120,
        governed_candidates=20,
        opportunities_reaching_cio=3,
    )

    stages = trust.opportunity_funnel_stages(snapshot)

    assert stages[2][0] == "Deep analysis"
    assert stages[2][1] == "Check needed"
    assert "Reported 120 exceeds the upstream cohort of 80" in stages[2][2]
    assert stages[2][3] is True


def test_entrypoints_install_trust_layer_after_retention_before_route_guard() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import today_trust_ui_runtime" in source
        retention_install = source.index("today_story_retention_runtime.install(")
        trust_install = source.index("today_trust_ui_runtime.install(")
        route_install = source.index("surface_route_isolation_runtime.install(")
        assert retention_install < trust_install < route_install
