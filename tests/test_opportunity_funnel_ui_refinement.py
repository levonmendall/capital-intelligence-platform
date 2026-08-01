from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import opportunity_funnel_ui_refinement as refinement


def test_partial_market_snapshot_removes_quote_denominator() -> None:
    snapshot = {
        "status": "partial",
        "quote_count": 12,
        "expected_quote_count": 15,
        "detail": "Only 12 of 15 governed instruments have usable top-of-book evidence.",
    }

    sanitized = refinement._sanitize_market_snapshot(snapshot)

    assert sanitized is not snapshot
    assert sanitized["detail"] == (
        "3 approved implementation instruments currently lack usable "
        "top-of-book evidence."
    )
    assert "12/15" not in sanitized["detail"]
    assert "12 of 15" not in sanitized["detail"]


def test_market_status_row_reports_implementation_state_not_denominator() -> None:
    rows = refinement._refined_status_rows(
        (
            (
                "Market status",
                "Closed · partial live coverage",
                "Provider-backed session and governed instrument coverage.",
            ),
            ("Portfolio action", "Hold", "No change."),
        )
    )

    assert rows[0][0] == "Market status"
    assert rows[0][1] == "Closed · implementation market data partial"
    assert "/" not in rows[0][1]
    assert rows[1] == ("Portfolio action", "Hold", "No change.")


def test_opportunity_scan_uses_actual_current_cycle_counts(monkeypatch) -> None:
    snapshot = SimpleNamespace(
        broad_assets_screened=4286,
        governed_candidates=173,
        opportunities_reaching_cio=11,
        snapshot_covered=3920,
        companies_deepened=240,
        strongest_alternative="GOVT — iShares U.S. Treasury Bond ETF",
        strongest_stage="Reached the governed CIO opportunity queue",
        main_reason="No candidate exceeded the governed capital alternative.",
        as_of=datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
        decision_reference="production-context:test",
        detail="Current-cycle production evidence.",
    )
    metric_calls: list[tuple[tuple[str, str, str], ...]] = []

    monkeypatch.setattr(
        refinement.concise.base,
        "load_opportunity_scan",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        refinement.concise.ui,
        "page_header",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        refinement.concise.ui,
        "metric_grid",
        lambda items, **kwargs: metric_calls.append(tuple(items)),
    )
    monkeypatch.setattr(
        refinement.concise.ui,
        "callout_card",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        refinement.st,
        "expander",
        lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(refinement.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(refinement.st, "caption", lambda *args, **kwargs: None)

    refinement.render_today_opportunity_scan(
        briefing={"portfolio_decision": "Maintain the current portfolio."}
    )

    assert metric_calls[0] == (
        ("Assets observed", "4,286", "Current governed scan"),
        (
            "Investment candidates considered",
            "173",
            "Complete candidate evidence",
        ),
        (
            "Decision eligible",
            "11",
            "Qualified for specialist and CIO review",
        ),
    )


def test_local_and_render_entrypoints_install_refinement() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import opportunity_funnel_ui_refinement" in source
        assert "opportunity_funnel_ui_refinement.install(app_impl)" in source
