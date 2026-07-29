from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/historical-backfill.yml")


def test_historical_workflow_publishes_durable_certification_ledger() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "issues: write" in source
    assert 'CERTIFICATION_ISSUE_NUMBER: "208"' in source
    assert "name: Publish running certification state" in source
    assert "name: Publish durable certification ledger" in source
    assert "-f state=pending" in source
    assert "Archive certification" in source
    assert "Canonical CIO replay" in source
    assert "historical-replay/canonical-cio" in source


def test_historical_workflow_reports_single_pass_completion_metrics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for output in (
        "records_written",
        "strict_records",
        "canonical_invoked",
        "blocked_cutoffs",
        "total_cutoffs",
        "relevant_records",
        "price_records",
        "macro_records",
        "archive_scans",
        "runtime_version",
    ):
        assert f"{output}:" in source

    assert 'canonical.get("archive_scan_count", 0)' in source
    assert 'canonical.get("runtime_version", "unknown")' in source
    assert "Research only: **true**" in source
    assert "Execution authorized: **false**" in source
    assert "Real money authorized: **false**" in source
    assert "Performance claims authorized: **false**" in source


def test_canonical_certification_has_no_legacy_shadow_blocker() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cancel-in-progress: true" in source
    assert "name: Run the production Canonical CIO over historical cutoffs" in source
    assert "Generate legacy strict monthly shadow replay" not in source
    assert "historical-shadow-replay.json" not in source
