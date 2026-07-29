from pathlib import Path


WORKFLOW = Path(".github/workflows/public-live-information.yml")
DOCUMENTATION = Path("docs/PUBLIC_LIVE_INFORMATION_COVERAGE.md")


def test_temporary_public_source_outages_do_not_fail_paper_operation() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Require public baseline availability" not in source
    assert "Publish public baseline status" in source
    assert '2|3)' in source
    assert "Public live-information baseline degraded" in source
    assert "listed-wrapper paper operator remains available" in source


def test_collector_implementation_failures_still_fail_the_workflow() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "The collector itself did not complete correctly" in source
    assert "exit 1" in source


def test_documentation_preserves_the_evidence_boundary() -> None:
    source = DOCUMENTATION.read_text(encoding="utf-8")

    assert "does not mark the application or listed-wrapper paper launch as failed" in source
    assert "Missing public evidence never becomes positive evidence" in source
    assert "remains blocked or abstains" in source
