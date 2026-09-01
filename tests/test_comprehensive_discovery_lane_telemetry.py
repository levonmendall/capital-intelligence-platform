from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import cached_transactional_comprehensive_discovery_lane as cached_lane
from operations import comprehensive_discovery_input_spool as spool
from operations import comprehensive_discovery_lane_telemetry as telemetry


def _timestamp(second: int) -> str:
    return datetime(2026, 8, 28, 23, 0, second, tzinfo=timezone.utc).isoformat()


def _request(
    tmp_path: Path,
    *,
    decision_epoch: str = "2026-08-28T23:00:00+00:00",
    filename: str = "request.json",
    release: str = "release-1",
) -> Path:
    policy_sha256 = "a" * 64
    identity = {
        "schema_version": spool._REQUEST_SCHEMA,
        "release": release,
        "decision_epoch": decision_epoch,
        "held_symbols": [],
        "tracked_symbols": [],
        "excluded_symbols": [],
        "policy_sha256": policy_sha256,
    }
    body = {
        **identity,
        "request_id": spool._digest(identity),
        "policy_blob": {
            "relative_path": "policy.pkl",
            "sha256": policy_sha256,
            "byte_count": 0,
        },
        **spool._authority_fields(),
    }
    path = tmp_path / filename
    spool._atomic_json(path, body)
    return path


def _request_id(path: Path) -> str:
    body = spool._load_json(path, schema=spool._REQUEST_SCHEMA)
    return str(body["request_id"])


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-1",
    }


def test_lane_telemetry_reports_cache_hits_and_post_hit_phase_timing(tmp_path) -> None:
    request = _request(tmp_path)
    values = _values(tmp_path)

    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        lane_started_at=_timestamp(0),
    )
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        structural_started_at=_timestamp(1),
        structural_cache_hit=True,
    )
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        structural_completed_at=_timestamp(2),
        publication_started_at=_timestamp(2),
    )
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        publication_completed_at=_timestamp(5),
        screening_started_at=_timestamp(5),
    )
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        screening_completed_at=_timestamp(10),
        lane_completed_at=_timestamp(11),
    )
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="fixed_income",
        index=1,
        lane_started_at=_timestamp(0),
        structural_started_at=_timestamp(1),
        structural_cache_hit=False,
        structural_completed_at=_timestamp(4),
        publication_started_at=_timestamp(4),
        publication_completed_at=_timestamp(6),
        screening_started_at=_timestamp(6),
        screening_completed_at=_timestamp(9),
        lane_completed_at=_timestamp(10),
    )

    public = telemetry.load_public_lane_telemetry(values)

    assert public is not None
    assert public["structural_cache_hits"] == 1
    assert public["structural_cache_misses"] == 1
    assert public["structural_cache_unknown"] == 0
    assert public["advisory_only"] is True
    assert public["watchdog_progress_authority"] is False
    assert public["evidence_certified"] is False
    assert public["decision_authority"] is False
    assert public["execution_authority"] is False
    assert public["paper_only"] is True
    assert public["real_money_authorized"] is False

    equity = public["lanes"][0]
    assert equity["asset_class"] == "us_equity"
    assert equity["structural_cache_hit"] is True
    assert equity["structural_elapsed_seconds"] == 1.0
    assert equity["publication_elapsed_seconds"] == 3.0
    assert equity["screening_elapsed_seconds"] == 5.0
    assert equity["total_elapsed_seconds"] == 11.0
    assert equity["post_hit_elapsed_seconds"] == 9.0


def test_new_request_resets_prior_lane_telemetry(tmp_path) -> None:
    values = _values(tmp_path)
    prior = _request(
        tmp_path,
        decision_epoch="2026-08-28T23:00:00+00:00",
        filename="prior-request.json",
    )
    telemetry.record_lane_phase(
        prior,
        values,
        asset_class="us_equity",
        index=0,
        lane_started_at=_timestamp(0),
        structural_cache_hit=True,
    )

    current = _request(
        tmp_path,
        decision_epoch="2026-08-28T23:01:00+00:00",
        filename="current-request.json",
    )
    telemetry.record_lane_phase(
        current,
        values,
        asset_class="future",
        index=9,
        lane_started_at=_timestamp(1),
        structural_cache_hit=False,
    )

    public = telemetry.load_public_lane_telemetry(values)
    assert public is not None
    assert public["request_id"] == _request_id(current)
    assert [item["asset_class"] for item in public["lanes"]] == ["future"]


def test_stale_epoch_writer_cannot_replace_newer_lane_telemetry(tmp_path) -> None:
    values = _values(tmp_path)
    stale = _request(
        tmp_path,
        decision_epoch="2026-08-28T23:00:00+00:00",
        filename="stale-request.json",
    )
    current = _request(
        tmp_path,
        decision_epoch="2026-08-28T23:01:00+00:00",
        filename="current-request.json",
    )

    telemetry.record_lane_phase(
        current,
        values,
        asset_class="future",
        index=9,
        lane_started_at=_timestamp(1),
        structural_cache_hit=True,
    )
    telemetry.record_lane_phase(
        stale,
        values,
        asset_class="us_equity",
        index=0,
        lane_started_at=_timestamp(2),
        structural_cache_hit=False,
    )

    public = telemetry.load_public_lane_telemetry(values)
    assert public is not None
    assert public["request_id"] == _request_id(current)
    assert public["decision_epoch"] == "2026-08-28T23:01:00+00:00"
    assert [item["asset_class"] for item in public["lanes"]] == ["future"]
    assert public["structural_cache_hits"] == 1
    assert public["structural_cache_misses"] == 0


def test_canonical_request_release_mismatch_is_not_recorded(tmp_path) -> None:
    request = _request(tmp_path, release="other-release")
    values = _values(tmp_path)

    try:
        telemetry.record_lane_phase(
            request,
            values,
            asset_class="us_equity",
            index=0,
            lane_started_at=_timestamp(0),
        )
    except ValueError as error:
        assert "release mismatch" in str(error)
    else:
        raise AssertionError("release-mismatched telemetry request was accepted")

    assert telemetry.load_public_lane_telemetry(values) is None


def test_public_lane_telemetry_rejects_authority_tampering(tmp_path) -> None:
    request = _request(tmp_path)
    values = _values(tmp_path)
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        lane_started_at=_timestamp(0),
    )

    path = tmp_path / telemetry._STATE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision_authority"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert telemetry.load_public_lane_telemetry(values) is None


def test_failed_lane_publishes_only_credential_safe_error_detail(tmp_path) -> None:
    request = _request(tmp_path)
    values = _values(tmp_path)
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="international_equity",
        index=4,
        lane_started_at=_timestamp(0),
        lane_failed_at=_timestamp(1),
        error_type="ComprehensiveDiscoverySpoolError",
        error_detail="provider publication produced no substantive signal",
    )

    public = telemetry.load_public_lane_telemetry(values)

    assert public is not None
    lane = public["lanes"][0]
    assert lane["error_type"] == "ComprehensiveDiscoverySpoolError"
    assert lane["error_detail"] == (
        "provider publication produced no substantive signal"
    )
    assert public["credential_safe"] is True
    assert public["advisory_only"] is True


def test_cached_lane_records_canonical_hit_and_phase_transitions(monkeypatch, tmp_path) -> None:
    events: list[dict[str, object]] = []
    asset_class = CandidateAssetClass.US_EQUITY
    source = datetime(2026, 8, 28, 22, 0, tzinfo=timezone.utc)
    requested = datetime(2026, 8, 28, 23, 0, tzinfo=timezone.utc)
    records = (SimpleNamespace(symbol="A"),)
    core = SimpleNamespace(
        _base=SimpleNamespace(
            scheduled_discovery_lanes=lambda _timestamp: frozenset({asset_class})
        )
    )

    monkeypatch.setattr(
        telemetry,
        "record_lane_phase",
        lambda _path, _values, *, asset_class, index, **updates: events.append(
            {"asset_class": asset_class, "index": index, **updates}
        ),
    )
    monkeypatch.setattr(
        cached_lane._structural,
        "load_structural_catalog",
        lambda *_args, **_kwargs: SimpleNamespace(
            records=records,
            raw_record_count=1,
            source_as_of=source,
        ),
    )
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_BUILD_DEEP_LANE",
        lambda *args, **kwargs: "screened",
    )
    monkeypatch.setattr(cached_lane, "_record_watchdog_phase", lambda _action: None)

    def canonical_transaction(request_path, values, *, asset_class_value, index):
        raw = cached_lane._load_catalog_records(
            core=core,
            values=values,
            policy=SimpleNamespace(version="policy-v1"),
            timestamp=requested,
            asset_class=asset_class,
        )
        merged = cached_lane._merge_certified_lane(
            core,
            raw,
            asset_class=asset_class,
            timestamp=requested,
        )
        assert merged == records
        assert cached_lane._build_deep_lane() == "screened"
        return "complete"

    monkeypatch.setattr(cached_lane, "_ORIGINAL_RUN_LANE_TRANSACTION", canonical_transaction)

    result = cached_lane._run_lane_transaction(
        _request(tmp_path),
        _values(tmp_path),
        asset_class_value=asset_class.value,
        index=0,
    )

    assert result == "complete"
    assert any(event.get("structural_cache_hit") is True for event in events)
    assert any("structural_completed_at" in event for event in events)
    assert any("publication_started_at" in event for event in events)
    assert any("publication_completed_at" in event for event in events)
    assert any("screening_started_at" in event for event in events)
    assert any("screening_completed_at" in event for event in events)
    assert any("lane_completed_at" in event for event in events)


def test_lane_telemetry_failure_is_fail_soft_for_canonical_transaction(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        telemetry,
        "record_lane_phase",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("telemetry unavailable")),
    )
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_RUN_LANE_TRANSACTION",
        lambda *args, **kwargs: "canonical-result",
    )

    result = cached_lane._run_lane_transaction(
        _request(tmp_path),
        _values(tmp_path),
        asset_class_value=CandidateAssetClass.US_EQUITY.value,
        index=0,
    )

    assert result == "canonical-result"


def test_cached_lane_redacts_failure_detail_before_advisory_publication(
    monkeypatch, tmp_path
) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        telemetry,
        "record_lane_phase",
        lambda _path, _values, *, asset_class, index, **updates: events.append(
            {"asset_class": asset_class, "index": index, **updates}
        ),
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("provider rejected token secret-value")

    monkeypatch.setattr(cached_lane, "_ORIGINAL_RUN_LANE_TRANSACTION", fail)
    values = {
        **_values(tmp_path),
        "EODHD_API_TOKEN": "secret-value",
    }

    try:
        cached_lane._run_lane_transaction(
            _request(tmp_path),
            values,
            asset_class_value=CandidateAssetClass.INTERNATIONAL_EQUITY.value,
            index=4,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("canonical failure was not preserved")

    failed = next(event for event in events if "lane_failed_at" in event)
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_detail"] == "provider rejected token [REDACTED]"
