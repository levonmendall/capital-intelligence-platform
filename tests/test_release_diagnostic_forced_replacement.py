from __future__ import annotations

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)
import run_bounded_manual_cio_diagnostic as bounded


def test_force_retry_primes_fresh_request_before_reference_readiness(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-536-repair",
    }
    original, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-536-repair",
        values=values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=values)
    assert claimed is not None
    finished = finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key=None,
        snapshot_identifier=None,
        detail="provider rate limited",
        values=values,
    )
    assert finished.request_id == original.request_id
    assert finished.state == "failed"

    bounded._prime_forced_replacement(values)

    replacement = latest_manual_cio_diagnostic(values=values)
    assert replacement is not None
    assert replacement.request_id != original.request_id
    assert replacement.state == "pending"
    assert replacement.requested_by == "render-release:release-536-repair"

    child_request, child_created = request_manual_cio_diagnostic(
        requested_by="render-release:release-536-repair",
        values=values,
    )
    assert child_created is False
    assert child_request.request_id == replacement.request_id
    child_claim = claim_manual_cio_diagnostic(values=values)
    assert child_claim is not None
    assert child_claim.request_id == replacement.request_id
    assert child_claim.state == "in_progress"


def test_force_retry_does_not_replace_active_request(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-active",
    }
    active, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-active",
        values=values,
    )
    assert created is True

    bounded._prime_forced_replacement(values)

    latest = latest_manual_cio_diagnostic(values=values)
    assert latest is not None
    assert latest.request_id == active.request_id
    assert latest.state == "pending"
