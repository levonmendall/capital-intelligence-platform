from __future__ import annotations

from types import SimpleNamespace

import portfolio_evidence_accumulation_ui as evidence_ui
import portfolio_only_runtime


def _summary() -> dict[str, object]:
    return {
        "successful": 1,
        "attempted": 4,
        "total": 4,
        "reached": 3,
        "as_of": "2026-08-19T20:15:00+00:00",
        "source": "Current all-market evaluation",
        "rows": [
            {
                "key": "us_equity",
                "asset_class": "U.S. equities",
                "status": "Evaluated",
                "detail": "500 cataloged · 80 deep analyzed · 12 selected",
            },
            {
                "key": "fx",
                "asset_class": "FX",
                "status": "In progress",
                "detail": "Market evidence qualified · terminal evaluation pending",
            },
            {
                "key": "fixed_income",
                "asset_class": "Fixed income",
                "status": "Failed",
                "detail": "Evaluation evidence failed · ProviderEvidenceError",
            },
            {
                "key": "commodity",
                "asset_class": "Commodities",
                "status": "Awaiting evaluation",
                "detail": "No current-cycle terminal evaluation is recorded for this asset class.",
            },
        ],
    }


def _historical_summary() -> dict[str, object]:
    summary = _summary()
    summary["source"] = "Latest completed global evaluation"
    summary["reached"] = 1
    summary["rows"] = [
        summary["rows"][0],
        {
            "key": "fx",
            "asset_class": "FX",
            "status": "Awaiting evaluation",
            "detail": "No current-cycle terminal evaluation is recorded for this asset class.",
        },
        {
            "key": "fixed_income",
            "asset_class": "Fixed income",
            "status": "Awaiting evaluation",
            "detail": "No current-cycle terminal evaluation is recorded for this asset class.",
        },
        {
            "key": "commodity",
            "asset_class": "Commodities",
            "status": "Awaiting evaluation",
            "detail": "No current-cycle terminal evaluation is recorded for this asset class.",
        },
    ]
    return summary


def test_evidence_accumulation_mirrors_crypto_information_hierarchy() -> None:
    html = evidence_ui.render_evidence_accumulation(_summary())

    assert "Evidence accumulation" in html
    assert "Certification evidence snapshot" in html
    assert "Read-only progress · thresholds unchanged" in html
    assert "Governed classes" in html
    assert "Reached now" in html
    assert "Evaluated" in html
    assert "In progress" in html
    assert "Awaiting" in html
    assert "Failed" in html
    assert "3 / 4" in html
    assert "1 / 4" in html
    assert "Snapshot coverage" not in html
    assert "Not in latest snapshot" not in html


def test_historical_fallback_never_uses_current_cycle_language() -> None:
    html = evidence_ui.render_evidence_accumulation(_historical_summary())

    assert "Latest completed global evaluation" in html
    assert "Snapshot coverage" in html
    assert "represented in completed snapshot" in html
    assert "Not in snapshot" in html
    assert "no record in completed snapshot" in html
    assert "Not in latest snapshot" in html
    assert "Represented" in html
    assert "latest completed snapshot" in html
    assert "No terminal record is present for this asset class in the latest completed snapshot." in html
    assert "current exact-release activity is tracked separately" in html
    assert "Reached now" not in html
    assert "Awaiting evaluation" not in html
    assert "Await the governed evaluation path; thresholds remain unchanged." not in html


def test_each_asset_class_gets_a_full_breakdown_card() -> None:
    html = evidence_ui.render_evidence_accumulation(_summary())

    assert html.count('class="asset-evidence-card"') == 4
    for asset_class in ("U.S. equities", "FX", "Fixed income", "Commodities"):
        assert asset_class in html
    for metric in ("Cataloged", "Deep analyzed", "Selected", "Reached", "Terminal", "Evaluated"):
        assert metric in html
    assert "500" in html
    assert "80" in html
    assert "12" in html
    assert "ProviderEvidenceError" in html
    assert "without lowering evidence or decision thresholds" in html


def test_missing_lane_counts_are_not_invented() -> None:
    html = evidence_ui.render_evidence_accumulation(_summary())

    # Only the completed U.S. equity row publishes catalog/deep/selected counts. Other
    # cards must display an em dash rather than fabricate crypto-style observations.
    assert "published universe count" in html
    assert "—" in html
    assert "Provider Ready" not in html
    assert "Observations" not in html
    assert "Forward ≥" not in html


def test_refinement_replaces_legacy_table_and_moves_evidence_after_metrics() -> None:
    base_html = (
        '<div class="cie-command-center">'
        '<section class="metrics"><div>capital</div></section>'
        '<section class="card section full"><div class="section-title">Asset class evaluation status</div>'
        '<div>legacy table</div></section>'
        '<section class="card section full"><div class="section-title">Decision pipeline status</div></section>'
        "</div>"
    )

    html = evidence_ui.refine_command_center_html(base_html, _summary())

    assert "legacy table" not in html
    assert "Asset class evaluation status" not in html
    assert html.index("capital") < html.index("Evidence accumulation")
    assert html.index("Evidence accumulation") < html.index("Decision pipeline status")


def test_evidence_accumulation_is_mobile_first_and_script_free() -> None:
    html = evidence_ui.render_evidence_accumulation(_summary())

    assert "@media(max-width:650px)" in html
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in html
    assert "<script" not in html
    assert "https://" not in html


def test_evidence_accumulation_escapes_read_model_content() -> None:
    summary = _summary()
    rows = list(summary["rows"])
    rows[0] = {
        **rows[0],
        "asset_class": '<img src=x onerror="boom">',
        "detail": "<script>alert(1)</script>",
    }
    summary["rows"] = rows

    html = evidence_ui.render_evidence_accumulation(summary)

    assert '<img src=x onerror="boom">' not in html
    assert "&lt;img src=x onerror=&quot;boom&quot;&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_install_refines_real_portfolio_command_center_once(monkeypatch) -> None:
    original = portfolio_only_runtime._command_center_html
    monkeypatch.delattr(portfolio_only_runtime, evidence_ui._ORIGINAL_ATTR, raising=False)
    try:
        evidence_ui.install(portfolio_only_runtime)
        installed = portfolio_only_runtime._command_center_html
        evidence_ui.install(portfolio_only_runtime)
        assert portfolio_only_runtime._command_center_html is installed

        html = installed(
            totals={"nav": 250_000.0, "cash": 250_000.0},
            mandate={
                "nav": 250_000.0,
                "cash": 250_000.0,
                "holdings": [],
                "trades": [],
                "snapshots": [],
            },
            briefing=None,
            construction=None,
            operating_status=SimpleNamespace(label="Operational", headline="Operational", detail="Current"),
            asset_class_evaluation=_summary(),
        )
        assert "Evidence accumulation" in html
        assert "Asset class evaluation status" not in html
        assert html.index("Starting capital") < html.index("Evidence accumulation")
        assert html.index("Evidence accumulation") < html.index("Equity curve")
    finally:
        portfolio_only_runtime._command_center_html = original
        monkeypatch.delattr(portfolio_only_runtime, evidence_ui._ORIGINAL_ATTR, raising=False)
