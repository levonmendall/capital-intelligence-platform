from __future__ import annotations

import all_market_certification_ui
import portfolio_evidence_accumulation_ui
from ui_reporting_time import format_reporting_timestamp


_TIMESTAMP = "2026-08-30T23:06:00+00:00"


def test_reporting_timestamp_uses_configured_pacific_timezone():
    rendered = format_reporting_timestamp(
        _TIMESTAMP,
        missing="missing",
        values={"CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE": "America/Los_Angeles"},
    )

    assert rendered == "Aug 30, 4:06 PM PDT"


def test_evidence_accumulation_uses_reporting_timezone(monkeypatch):
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE", "America/Los_Angeles")

    rendered = portfolio_evidence_accumulation_ui.render_evidence_accumulation(
        {
            "as_of": _TIMESTAMP,
            "source": "Current all-market evaluation",
            "total": 13,
            "reached": 1,
            "rows": [
                {
                    "key": "us_equity",
                    "asset_class": "U.S. equities",
                    "status": "Evaluated",
                    "detail": "1 cataloged · 1 deep analyzed · 1 selected",
                }
            ],
        }
    )

    assert "Certification evidence snapshot Aug 30, 4:06 PM PDT" in rendered
    assert "11:06 PM" not in rendered


def test_certification_cutoff_uses_same_reporting_timezone(monkeypatch):
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE", "America/Los_Angeles")

    rendered = all_market_certification_ui.render_certification_banner(
        {
            "certified": True,
            "release_sha": "abcdef123456",
            "certification_id": "certificate-123456",
            "certification_state": "CERTIFIED",
            "evidence_cutoff": _TIMESTAMP,
            "verifier_source_id": "verifier",
            "coverage": {"represented_count": 13, "required_count": 13},
        }
    )

    assert "Evidence cutoff Aug 30, 4:06 PM PDT" in rendered


def test_invalid_reporting_timezone_falls_back_to_utc():
    rendered = format_reporting_timestamp(
        _TIMESTAMP,
        missing="missing",
        values={"CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE": "Not/A_Timezone"},
    )

    assert rendered == "Aug 30, 11:06 PM UTC"
