from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_manual_cio_diagnostic as diagnostic
from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic


def test_disabled_diagnostic_does_not_touch_runtime(monkeypatch, tmp_path: Path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-disabled",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "false",
    }

    monkeypatch.setattr(
        diagnostic.ApiSettings,
        "from_env",
        lambda *_: (_ for _ in ()).throw(AssertionError("runtime must not start")),
    )

    assert diagnostic.run_diagnostic_once(values=values) == 0
    assert latest_manual_cio_diagnostic(values=values) is None


def test_context_failure_is_persisted_and_credentials_are_redacted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    secret = "super-secret-provider-token"
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-failed",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN": secret,
    }
    settings = SimpleNamespace(
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
    )
    context = SimpleNamespace(
        ready=False,
        cycle_key="manual-context:release-failed",
        detail=f"provider request failed?api_token={secret}",
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

    record = latest_manual_cio_diagnostic(values=values)
    assert record is not None
    assert record.state == "failed"
    assert record.cycle_key == "manual-context:release-failed"
    assert secret not in (record.detail or "")
    assert "[REDACTED]" in (record.detail or "")

    monkeypatch.setattr(
        diagnostic,
        "build_worker",
        lambda _: (_ for _ in ()).throw(AssertionError("same release must not rerun")),
    )
    assert diagnostic.run_diagnostic_once(values=values) == 0


def test_successful_diagnostic_uses_triggered_cycle_and_paper_controls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-success",
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "true",
    }
    settings = SimpleNamespace(
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
    )
    context = SimpleNamespace(
        ready=True,
        cycle_key="manual-context:release-success",
        detail="ready",
        decision_as_of=diagnostic.datetime.now(diagnostic.timezone.utc),
    )
    calls = []

    class Worker:
        def run_triggered(self, trigger_key, *, now, decision_as_of):
            calls.append((trigger_key, now, decision_as_of))
            return SimpleNamespace(
                cycle_key="canonical-cio:test:event:manual",
                status="completed",
                detail=None,
                snapshot_identifier="briefing-123",
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
    published = []
    monkeypatch.setattr(
        diagnostic,
        "publish_pending_transaction_report",
        lambda **kwargs: published.append(kwargs),
    )

    assert diagnostic.run_diagnostic_once(values=values) == 0
    assert len(calls) == 1
    assert calls[0][0].startswith("manual-diagnostic-")
    assert published[0]["execution_state"] == "idle"

    record = latest_manual_cio_diagnostic(values=values)
    assert record is not None
    assert record.state == "completed"
    assert record.snapshot_identifier == "briefing-123"
    assert record.cycle_key == "canonical-cio:test:event:manual"
