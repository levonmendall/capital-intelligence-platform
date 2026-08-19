"""Regressions for the post-public/pre-DAG progress seam."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import requests

from operations import evidence_preparation_progress as preparation
from operations import public_live_requirement_qualification as public_progress
from operations import release_prequalification_parent_watchdog as watchdog


def test_progress_round_trip_is_exact_release_and_non_authoritative(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }

    written = preparation.record_evidence_preparation_progress(
        values,
        completed_provider_calls=7,
    )
    loaded = preparation.load_evidence_preparation_progress(values)

    assert written is not None
    assert loaded is not None
    assert loaded["release_sha"] == "release-test"
    assert loaded["stage"] == "post-public-provider-io"
    assert loaded["progress_semantics"] == "distinct-provider-request-work-units"
    assert loaded["metrics"] == {"provider_calls_completed": 7}
    assert loaded["credential_safe"] is True
    assert loaded["decision_authority"] is False
    assert loaded["candidate_authority"] is False
    assert loaded["sizing_authority"] is False
    assert loaded["construction_authority"] is False
    assert loaded["execution_authority"] is False
    assert loaded["paper_only"] is True
    assert loaded["real_money_authorized"] is False

    different_release = dict(values, CAPITAL_INTELLIGENCE_RELEASE="other-release")
    assert preparation.load_evidence_preparation_progress(different_release) is None


def test_integrity_change_invalidates_progress(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    preparation.record_evidence_preparation_progress(values, completed_provider_calls=2)
    path = preparation._path(values)
    assert path is not None
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["metrics"]["provider_calls_completed"] = 999
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert preparation.load_evidence_preparation_progress(values) is None


def test_request_hook_records_only_distinct_work_units_after_public_qualification(
    monkeypatch,
    tmp_path,
) -> None:
    state = {
        "state": "qualifying",
        "pending_count": 1,
        "failed_count": 0,
    }
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    captured: list[int] = []

    def canonical_request(_session, *_args, **_kwargs):
        return "provider-result"

    monkeypatch.setattr(requests.sessions.Session, "request", canonical_request)
    monkeypatch.setattr(
        public_progress,
        "load_public_live_requirement_progress",
        lambda _values: dict(state),
    )
    monkeypatch.setattr(
        preparation,
        "record_evidence_preparation_progress",
        lambda _values, *, completed_provider_calls: captured.append(completed_provider_calls),
    )

    preparation.install_post_public_provider_progress(values)
    session = requests.Session()

    assert session.request("GET", "https://example.invalid", params={"page": 1}) == "provider-result"
    assert captured == []

    state.update(state="qualified", pending_count=0)
    assert session.request("GET", "https://example.invalid", params={"page": 1}) == "provider-result"
    assert session.request("GET", "https://example.invalid", params={"page": 1}) == "provider-result"
    assert session.request("GET", "https://example.invalid", params={"page": 2}) == "provider-result"
    assert captured == [1, 2]


def test_request_hook_duplicate_failure_does_not_heartbeat_or_swallow_exception(
    monkeypatch,
    tmp_path,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    captured: list[int] = []

    def failing_request(_session, *_args, **_kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(requests.sessions.Session, "request", failing_request)
    monkeypatch.setattr(
        public_progress,
        "load_public_live_requirement_progress",
        lambda _values: {
            "state": "qualified",
            "pending_count": 0,
            "failed_count": 0,
        },
    )
    monkeypatch.setattr(
        preparation,
        "record_evidence_preparation_progress",
        lambda _values, *, completed_provider_calls: captured.append(completed_provider_calls),
    )

    preparation.install_post_public_provider_progress(values)
    session = requests.Session()

    for _ in range(2):
        try:
            session.request("GET", "https://example.invalid", params={"page": 1})
        except RuntimeError as error:
            assert str(error) == "provider failed"
        else:  # pragma: no cover - makes swallowed exceptions explicit.
            raise AssertionError("provider exception was swallowed by progress hook")

    assert captured == [1]


def test_parent_watchdog_prefers_newer_pre_dag_progress(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    public_at = started + timedelta(seconds=2)
    preparation_at = started + timedelta(seconds=5)

    monkeypatch.setattr(watchdog, "load_reference_prequalification_progress", lambda _values: None)
    monkeypatch.setattr(
        watchdog,
        "load_public_live_requirement_progress",
        lambda _values: {
            "updated_at": public_at.isoformat(),
            "state": "qualified",
            "active_required_information": None,
            "required_count": 13,
            "qualified_count": 13,
            "pending_count": 0,
            "failed_count": 0,
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_evidence_preparation_progress",
        lambda _values: {
            "updated_at": preparation_at.isoformat(),
            "stage": "post-public-provider-io",
            "metrics": {"provider_calls_completed": 11},
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_release_certification_dag_progress",
        lambda _values, started_at=None: None,
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "discovery_preparation"
    assert progress.component == "post-public-provider-io"
    assert progress.state == "running"
    assert progress.metrics == {"provider_calls_completed": 11}
    assert progress.stall_limit_seconds == 180


def test_parent_watchdog_ignores_pre_dag_progress_from_prior_attempt(monkeypatch) -> None:
    started = datetime.now(timezone.utc)
    stale = started - timedelta(seconds=1)

    monkeypatch.setattr(watchdog, "load_reference_prequalification_progress", lambda _values: None)
    monkeypatch.setattr(watchdog, "load_public_live_requirement_progress", lambda _values: None)
    monkeypatch.setattr(
        watchdog,
        "load_evidence_preparation_progress",
        lambda _values: {
            "updated_at": stale.isoformat(),
            "stage": "post-public-provider-io",
            "metrics": {"provider_calls_completed": 50},
        },
    )
    monkeypatch.setattr(
        watchdog,
        "load_release_certification_dag_progress",
        lambda _values, started_at=None: None,
    )

    progress = watchdog.observe_current_prequalification_progress({}, started_at=started)

    assert progress.phase == "reference_binding"
    assert progress.component == "release-reference-manifest"
