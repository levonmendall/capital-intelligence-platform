from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)
from prime_release_cio_diagnostic import prime_release_diagnostic_request


def _values(tmp_path: Path, release: str) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": release,
    }


def _write_owner_lease(tmp_path: Path, *, request_id: str, pid: int) -> None:
    (tmp_path / "manual-cio-diagnostic-owner.json").write_text(
        json.dumps(
            {
                "request_id": request_id,
                "pid": pid,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_primer_replaces_prior_terminal_release_with_current_pending_request(
    tmp_path: Path,
) -> None:
    prior_values = _values(tmp_path, "release-prior")
    prior, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-prior",
        values=prior_values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=prior_values)
    assert claimed is not None
    finish_manual_cio_diagnostic(
        claimed,
        succeeded=True,
        cycle_key="canonical-cio:prior-context",
        snapshot_identifier="prior-snapshot",
        detail="prior terminal result",
        values=prior_values,
    )

    current_values = _values(tmp_path, "release-current")
    assert prime_release_diagnostic_request(current_values) == 0

    current = latest_manual_cio_diagnostic(values=current_values)
    assert current is not None
    assert current.state == "pending"
    assert current.requested_by == "render-release:release-current"
    assert current.request_id != prior.request_id
    assert current.cycle_key is None
    assert current.snapshot_identifier is None
    assert current.to_dict()["paper_only"] is True
    assert current.to_dict()["real_money_authorized"] is False


def test_primer_supersedes_prior_release_pending_with_current_pending_request(
    tmp_path: Path,
) -> None:
    prior_values = _values(tmp_path, "release-prior")
    prior, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-prior",
        values=prior_values,
    )
    assert created is True
    assert prior.state == "pending"

    current_values = _values(tmp_path, "release-current")
    assert prime_release_diagnostic_request(current_values) == 0

    current = latest_manual_cio_diagnostic(values=current_values)
    assert current is not None
    assert current.state == "pending"
    assert current.requested_by == "render-release:release-current"
    assert current.request_id != prior.request_id
    assert current.cycle_key is None
    assert current.snapshot_identifier is None
    assert current.to_dict()["paper_only"] is True
    assert current.to_dict()["real_money_authorized"] is False


def test_primer_preserves_same_release_pending_request(tmp_path: Path) -> None:
    values = _values(tmp_path, "release-current")
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-current",
        values=values,
    )
    assert created is True

    assert prime_release_diagnostic_request(values) == 0

    preserved = latest_manual_cio_diagnostic(values=values)
    assert preserved is not None
    assert preserved.request_id == request.request_id
    assert preserved.requested_by == "render-release:release-current"
    assert preserved.state == "pending"


def test_primer_supersedes_orphaned_prior_release_in_progress_request(
    tmp_path: Path,
) -> None:
    prior_values = _values(tmp_path, "release-prior")
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-prior",
        values=prior_values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=prior_values)
    assert claimed is not None
    assert claimed.state == "in_progress"

    current_values = _values(tmp_path, "release-current")
    assert prime_release_diagnostic_request(current_values) == 0

    current = latest_manual_cio_diagnostic(values=current_values)
    assert current is not None
    assert current.request_id != request.request_id
    assert current.requested_by == "render-release:release-current"
    assert current.state == "pending"
    assert current.cycle_key is None
    assert current.snapshot_identifier is None
    assert current.to_dict()["paper_only"] is True
    assert current.to_dict()["real_money_authorized"] is False


def test_primer_preserves_live_prior_release_in_progress_owner(
    tmp_path: Path,
) -> None:
    prior_values = _values(tmp_path, "release-prior")
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-prior",
        values=prior_values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=prior_values)
    assert claimed is not None
    assert claimed.state == "in_progress"
    _write_owner_lease(tmp_path, request_id=request.request_id, pid=os.getpid())

    current_values = _values(tmp_path, "release-current")
    assert prime_release_diagnostic_request(current_values) == 0

    preserved = latest_manual_cio_diagnostic(values=current_values)
    assert preserved is not None
    assert preserved.request_id == request.request_id
    assert preserved.requested_by == "render-release:release-prior"
    assert preserved.state == "in_progress"


def test_primer_preserves_same_release_in_progress_request_without_repriming(
    tmp_path: Path,
) -> None:
    values = _values(tmp_path, "release-current")
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-current",
        values=values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=values)
    assert claimed is not None
    assert claimed.state == "in_progress"

    assert prime_release_diagnostic_request(values) == 0

    preserved = latest_manual_cio_diagnostic(values=values)
    assert preserved is not None
    assert preserved.request_id == request.request_id
    assert preserved.requested_by == "render-release:release-current"
    assert preserved.state == "in_progress"


def test_primer_does_not_duplicate_terminal_record_for_same_exact_release(
    tmp_path: Path,
) -> None:
    values = _values(tmp_path, "release-current")
    request, created = request_manual_cio_diagnostic(
        requested_by="render-release:release-current",
        values=values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=values)
    assert claimed is not None
    terminal = finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key="canonical-cio:current-context",
        snapshot_identifier=None,
        detail="fail closed",
        values=values,
    )

    assert prime_release_diagnostic_request(values) == 0

    preserved = latest_manual_cio_diagnostic(values=values)
    assert preserved is not None
    assert preserved.request_id == terminal.request_id
    assert preserved.state == "failed"


def test_primer_disabled_is_noop(tmp_path: Path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "false",
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
    }

    assert prime_release_diagnostic_request(values) == 0
    assert latest_manual_cio_diagnostic(values=values) is None
