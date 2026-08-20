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
