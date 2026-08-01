from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import operating_intelligence_ui as operating_ui
import opportunity_scan_resilience
from production_context_state_resilience import (
    attempt_state_path,
    invalidate_reuse_preserving_success,
    recording_context_preparer,
    successful_state_path,
)


def _settings(tmp_path: Path):
    return SimpleNamespace(portfolio_database=tmp_path / "canonical_portfolio.db")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _successful_payload() -> dict[str, object]:
    return {
        "schema_version": "production-context-publication-state.v5-comprehensive-markets",
        "cycle_key": "canonical-cio:America/Los_Angeles:2026-08-01",
        "decision_as_of": "2026-08-01T14:00:00+00:00",
        "context_identifier": "production-context:paper-pilot:success",
        "screening_cycle_identifier": "screening:paper-pilot:success",
        "candidate_count": 7,
        "qualified_candidate_count": 2,
        "equity_discovery": {
            "screened_asset_count": 2500,
            "snapshot_covered_count": 1800,
            "selected_count": 30,
        },
    }


def test_reuse_invalidation_preserves_the_complete_last_successful_scan(tmp_path) -> None:
    settings = _settings(tmp_path)
    path = successful_state_path(settings)
    original = _successful_payload()
    _write_json(path, original)

    invalidate_reuse_preserving_success(settings)

    preserved = json.loads(path.read_text(encoding="utf-8"))
    assert preserved["decision_as_of"] == original["decision_as_of"]
    assert preserved["context_identifier"] == original["context_identifier"]
    assert preserved["candidate_count"] == 7
    assert preserved["qualified_candidate_count"] == 2
    assert preserved["equity_discovery"] == original["equity_discovery"]
    assert preserved["last_successful_cycle_key"] == original["cycle_key"]
    assert preserved["cycle_key"].startswith("refresh-required:")
    assert preserved["last_successful_state_preserved"] is True


@dataclass(frozen=True)
class _PublicationResult:
    state: str
    detail: str
    cycle_key: str = "canonical-cio:test"
    decision_as_of: datetime | None = None

    @property
    def ready(self) -> bool:
        return self.state in {"ready", "reused"}

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "detail": self.detail,
            "cycle_key": self.cycle_key,
            "decision_as_of": (
                None if self.decision_as_of is None else self.decision_as_of.isoformat()
            ),
            "candidate_count": 0,
            "exclusion_count": 10,
        }


def test_blocked_refresh_records_exact_failure_without_erasing_success(tmp_path) -> None:
    settings = _settings(tmp_path)
    state_path = successful_state_path(settings)
    _write_json(state_path, _successful_payload())
    invalidate_reuse_preserving_success(settings)
    preserved_before = state_path.read_text(encoding="utf-8")

    def blocked_preparer(**_kwargs):
        return _PublicationResult(
            state="blocked",
            detail="Cross-market evidence collection failed: provider timeout",
        )

    result = recording_context_preparer(blocked_preparer)(
        settings=settings,
        scheduled_for=datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc),
    )

    assert result.state == "blocked"
    assert state_path.read_text(encoding="utf-8") == preserved_before
    attempt = json.loads(attempt_state_path(settings).read_text(encoding="utf-8"))
    assert attempt["state"] == "blocked"
    assert "provider timeout" in attempt["detail"]
    assert attempt["completed_at"] is not None
    assert attempt["paper_only"] is True
    assert attempt["real_money_authorized"] is False


def test_exception_refresh_records_failure_and_keeps_success(tmp_path) -> None:
    settings = _settings(tmp_path)
    state_path = successful_state_path(settings)
    _write_json(state_path, _successful_payload())
    invalidate_reuse_preserving_success(settings)
    preserved_before = state_path.read_text(encoding="utf-8")

    def failed_preparer(**_kwargs):
        raise RuntimeError("temporary discovery outage")

    wrapped = recording_context_preparer(failed_preparer)
    try:
        wrapped(
            settings=settings,
            scheduled_for=datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc),
        )
    except RuntimeError as error:
        assert "temporary discovery outage" in str(error)
    else:
        raise AssertionError("the governed failure must remain fail-closed")

    assert state_path.read_text(encoding="utf-8") == preserved_before
    attempt = json.loads(attempt_state_path(settings).read_text(encoding="utf-8"))
    assert attempt["state"] == "failed"
    assert "RuntimeError: temporary discovery outage" in attempt["detail"]


def _snapshot(*, as_of: datetime | None):
    return operating_ui.OpportunityScanSnapshot(
        state="available" if as_of is not None else "unavailable",
        as_of=as_of,
        broad_assets_screened=2500 if as_of is not None else None,
        snapshot_covered=1800 if as_of is not None else None,
        companies_deepened=30 if as_of is not None else None,
        governed_candidates=7 if as_of is not None else None,
        opportunities_reaching_cio=2 if as_of is not None else None,
        strongest_alternative="KLAC — KLA Corporation" if as_of is not None else "Unavailable",
        strongest_stage="Reached the governed CIO opportunity queue" if as_of is not None else "Awaiting first scan",
        main_reason="Expected return did not clear the cash hurdle." if as_of is not None else "The governed state is unavailable.",
        decision_reference="production-context:success" if as_of is not None else "Unavailable",
        detail="Counts describe process coverage, not expected performance.",
    )


def test_ui_keeps_last_successful_counts_and_explains_latest_blocker(
    monkeypatch,
    tmp_path,
) -> None:
    settings = _settings(tmp_path)
    scan_at = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    _write_json(
        attempt_state_path(settings),
        {
            "state": "blocked",
            "started_at": (scan_at + timedelta(hours=3)).isoformat(),
            "completed_at": (scan_at + timedelta(hours=3, minutes=2)).isoformat(),
            "detail": "Paper-universe provider certification failed: TimeoutError",
            "cycle_key": "canonical-cio:test",
        },
    )
    monkeypatch.setattr(operating_ui, "_runtime_settings", lambda: settings)

    decorated = opportunity_scan_resilience._decorate_snapshot(
        _snapshot(as_of=scan_at)
    )

    assert decorated.state == "stale"
    assert decorated.broad_assets_screened == 2500
    assert decorated.snapshot_covered == 1800
    assert decorated.companies_deepened == 30
    assert decorated.governed_candidates == 7
    assert decorated.opportunities_reaching_cio == 2
    assert "Latest governed opportunity-scan refresh did not complete" in decorated.detail
    assert "TimeoutError" in decorated.detail
    assert "Showing the last successful scan" in decorated.detail
    assert "No counts were erased" in decorated.detail


def test_ui_reports_first_scan_blocker_without_inventing_counts(
    monkeypatch,
    tmp_path,
) -> None:
    settings = _settings(tmp_path)
    now = datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc)
    _write_json(
        attempt_state_path(settings),
        {
            "state": "failed",
            "started_at": now.isoformat(),
            "completed_at": (now + timedelta(minutes=1)).isoformat(),
            "detail": "Complete opportunity search is unavailable",
            "cycle_key": "canonical-cio:first",
        },
    )
    monkeypatch.setattr(operating_ui, "_runtime_settings", lambda: settings)

    decorated = opportunity_scan_resilience._decorate_snapshot(_snapshot(as_of=None))

    assert decorated.broad_assets_screened is None
    assert decorated.snapshot_covered is None
    assert decorated.governed_candidates is None
    assert decorated.opportunities_reaching_cio is None
    assert "Complete opportunity search is unavailable" in decorated.main_reason
    assert "No prior successful production scan is available" in decorated.detail


def test_active_entrypoints_install_resilience_after_render_nonblocking_binding() -> None:
    local_source = Path("app.py").read_text(encoding="utf-8")
    render_source = Path("render_app.py").read_text(encoding="utf-8")
    operator_source = Path("run_autonomous_paper_operator.py").read_text(
        encoding="utf-8"
    )

    assert "opportunity_scan_resilience.install()" in local_source
    assert render_source.index("prepare_render_data_runtime()") < render_source.index(
        "opportunity_scan_resilience.install()"
    )
    assert "invalidate_reuse_preserving_success(settings)" in operator_source
    assert "recording_context_preparer(" in operator_source
    assert ".unlink()" not in operator_source
