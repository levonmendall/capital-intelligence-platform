from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_manual_cio_diagnostic as diagnostic
from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic


def test_successful_diagnostic_preserves_persisted_context_cycle_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-context-lineage",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
    }
    # The production diagnostic intentionally defers application imports until the
    # governed phase that needs them. Load only the coordination/configuration boundary
    # before replacing those dependencies with deterministic test doubles.
    diagnostic._load_coordination_dependencies()
    settings = SimpleNamespace(
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
    )
    context = SimpleNamespace(
        ready=True,
        cycle_key="daily-cio:context-cycle",
        detail="ready",
        decision_as_of=diagnostic.datetime.now(diagnostic.timezone.utc),
    )

    class Worker:
        def run_triggered(self, trigger_key, *, now, decision_as_of):
            assert trigger_key.startswith("manual-diagnostic-")
            assert decision_as_of == context.decision_as_of
            return SimpleNamespace(
                cycle_key="canonical-cio:triggered-cycle",
                status="completed",
                detail=None,
                snapshot_identifier="briefing-context-lineage",
            )

        def dispatch_pending(self):
            return ()

    monkeypatch.setattr(diagnostic.ApiSettings, "from_env", lambda _: settings)
    monkeypatch.setattr(
        diagnostic.OperationalSettings,
        "from_env",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(diagnostic, "configure_logging", lambda _: None)
    monkeypatch.setattr(diagnostic, "ensure_canonical_portfolio_store", lambda _: None)
    monkeypatch.setattr(diagnostic, "build_worker", lambda _: Worker())
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
    monkeypatch.setattr(diagnostic, "_payloads", lambda *_args, **_kwargs: ({}, {}))
    monkeypatch.setattr(diagnostic, "paper_trading_launch_open", lambda _now: True)
    monkeypatch.setattr(
        diagnostic,
        "attempt_paper_execution",
        lambda **_: SimpleNamespace(state="idle"),
    )
    monkeypatch.setattr(
        diagnostic,
        "publish_pending_transaction_report",
        lambda **_: None,
    )

    assert diagnostic.run_diagnostic_once(values=values) == 0

    record = latest_manual_cio_diagnostic(values=values)
    assert record is not None
    assert record.state == "completed"
    assert record.cycle_key == context.cycle_key
    assert record.cycle_key != "canonical-cio:triggered-cycle"
    assert record.snapshot_identifier == "briefing-context-lineage"
    assert record.to_dict()["paper_only"] is True
    assert record.to_dict()["real_money_authorized"] is False
