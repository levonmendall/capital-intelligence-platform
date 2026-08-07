from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import run_manual_cio_diagnostic as diagnostic
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)


@pytest.mark.parametrize("prior_release", ("release-old", "release-new"))
def test_release_start_recovers_interrupted_prior_process(
    monkeypatch,
    tmp_path: Path,
    capsys,
    prior_release: str,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-new",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
    }
    prior, created = request_manual_cio_diagnostic(
        requested_by=f"render-release:{prior_release}",
        values=values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(values=values)
    assert claimed is not None
    assert claimed.request_id == prior.request_id
    assert claimed.state == "in_progress"

    settings = SimpleNamespace(
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
    )
    context = SimpleNamespace(
        ready=False,
        cycle_key="manual-context:release-new",
        detail="fresh diagnostic reached the governed context boundary",
    )
    monkeypatch.setattr(diagnostic.ApiSettings, "from_env", lambda _: settings)
    monkeypatch.setattr(
        diagnostic.OperationalSettings,
        "from_env",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(diagnostic, "configure_logging", lambda _: None)
    monkeypatch.setattr(diagnostic, "ensure_canonical_portfolio_store", lambda _: None)
    monkeypatch.setattr(diagnostic, "build_worker", lambda _: SimpleNamespace())
    monkeypatch.setattr(
        diagnostic,
        "recording_context_preparer",
        lambda _preparer: lambda **_: context,
    )
    monkeypatch.setattr(
        diagnostic,
        "collect_public_live_information_if_due",
        lambda **_: SimpleNamespace(state="available"),
    )
    monkeypatch.setattr(diagnostic, "invalidate_reuse_preserving_success", lambda _: None)

    assert diagnostic.run_diagnostic_once(values=values) == 3

    current = latest_manual_cio_diagnostic(values=values)
    assert current is not None
    assert current.request_id != prior.request_id
    assert current.requested_by == "render-release:release-new"
    assert current.state == "failed"
    assert current.cycle_key == "manual-context:release-new"
    output = capsys.readouterr().out
    assert "manual_cio_diagnostic_interrupted_recovered" in output
