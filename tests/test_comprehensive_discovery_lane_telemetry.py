from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import cached_transactional_comprehensive_discovery_lane as cached_lane
from operations import comprehensive_discovery_lane_telemetry as telemetry


def _timestamp(second: int) -> str:
    return datetime(2026, 8, 28, 23, 0, second, tzinfo=timezone.utc).isoformat()


def _request(tmp_path: Path, *, request_id: str = "request-1") -> Path:
    path = tmp_path / "request.json"
    path.write_text(
        json.dumps(
            {
                "request_id": request_id,
                "decision_epoch": "2026-08-28T23:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return path


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
    request = _request(tmp_path, request_id="request-1")
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="us_equity",
        index=0,
        lane_started_at=_timestamp(0),
        structural_cache_hit=True,
    )

    request = _request(tmp_path, request_id="request-2")
    telemetry.record_lane_phase(
        request,
        values,
        asset_class="future",
        index=9,
        lane_started_at=_timestamp(1),
        structural_cache_hit=False,
    )

    public = telemetry.load_public_lane_telemetry(values)
    assert public is not None
    assert public["request_id"] == "request-2"
    assert [item["asset_class"] for item in public["lanes"]] == ["future"]


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
