from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import epoch_scoped_provider_acquisition as fanout


def _epoch() -> datetime:
    return datetime(2026, 8, 28, 16, 19, tzinfo=timezone.utc)


def test_non_render_never_spawns_provider_fanout(monkeypatch, tmp_path) -> None:
    def unexpected_popen(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("non-Render certification must keep the canonical serial path")

    report = fanout.run_provider_acquisition_fanout(
        tmp_path / "request.json",
        values={"RENDER": "false"},
        decision_epoch=_epoch(),
        popen=unexpected_popen,
    )

    assert report == {
        "attempted": False,
        "reason": "non_render",
        "completed": 0,
        "failed": 0,
    }


def test_provider_fanout_serially_prewarms_structure_then_overlaps_provider_io(
    monkeypatch, tmp_path
) -> None:
    lanes = tuple(
        item
        for item in CandidateAssetClass
        if item not in {CandidateAssetClass.OTHER, CandidateAssetClass.OPTION}
    )[:5]
    monkeypatch.setattr(
        fanout,
        "_scheduled_lane_items",
        lambda _epoch: tuple(enumerate(lanes)),
    )
    monkeypatch.setattr(fanout, "_fanout_budget_seconds", lambda *_args, **_kwargs: 30.0)
    monkeypatch.setattr(fanout.time, "sleep", lambda _seconds: None)

    created = []

    class FakeProcess:
        def __init__(self, pid: int, *, structural: bool) -> None:
            self.pid = pid
            self.structural = structural
            self.poll_count = 0

        def poll(self):
            if self.structural:
                return 0
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(command, **kwargs):
        command = tuple(command)
        process = FakeProcess(
            10_000 + len(created),
            structural="--prepare-structure" in command,
        )
        created.append((command, dict(kwargs), process))
        return process

    report = fanout.run_provider_acquisition_fanout(
        tmp_path / "request.json",
        values={
            "RENDER": "true",
            fanout._WORKERS_ENV: "3",
        },
        decision_epoch=_epoch(),
        popen=fake_popen,
    )

    structural = [item for item in created if "--prepare-structure" in item[0]]
    provider = [item for item in created if "--prepare-structure" not in item[0]]
    assert len(structural) == len(lanes)
    assert len(provider) == len(lanes)
    assert max(created.index(item) for item in structural) < min(
        created.index(item) for item in provider
    )
    assert report["structural_prewarm_attempted"] == len(lanes)
    assert report["structural_prewarm_completed"] == len(lanes)
    assert report["structural_prewarm_failed"] == 0
    assert report["structural_prewarm_maximum_parallel"] == 1
    assert report["provider_attempted_lanes"] == len(lanes)
    assert report["completed"] == len(lanes)
    assert report["failed"] == 0
    assert report["maximum_parallel"] == 3
    assert report["worker_limit"] == 3
    assert report["structural_reconstruction_parallelized"] is False
    assert report["limited_publication_promoted"] is False
    assert report["outer_process_group_inherited"] is True
    assert report["evidence_certified"] is False
    assert report["decision_authority"] is False
    assert report["execution_authority"] is False
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False
    assert all(item[1]["start_new_session"] is False for item in created)


def test_provider_fanout_preserves_downstream_epoch_reserve(monkeypatch) -> None:
    from operations import continuous_evidence_plane as plane

    monkeypatch.setattr(plane, "_max_age_seconds", lambda _values: 900.0)
    epoch = _epoch()

    assert fanout._fanout_budget_seconds(
        epoch,
        {},
        now=epoch + timedelta(seconds=100),
    ) == 300.0

    assert fanout._fanout_budget_seconds(
        epoch,
        {},
        now=epoch + timedelta(seconds=500),
    ) == 0.0


def test_cold_release_structural_prewarm_uses_canonical_merge_without_provider_or_screening(
    monkeypatch, tmp_path
) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import bounded_provider_preselection_publication as publication
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import comprehensive_market_discovery as facade
    from operations import transactional_comprehensive_discovery_lane as transaction

    asset_class = next(
        item
        for item in CandidateAssetClass
        if item not in {CandidateAssetClass.OTHER, CandidateAssetClass.OPTION}
    )
    timestamp = _epoch()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")

    @dataclass(frozen=True)
    class Policy:
        version: str = "policy-v1"

    policy = Policy()
    raw = (SimpleNamespace(symbol="RAW"),)
    merged = (SimpleNamespace(symbol="A"), SimpleNamespace(symbol="B"))
    cache = []
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, policy),
    )
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)

    def bind_fingerprint(values):
        values[structural._REFERENCE_STRUCTURAL_FINGERPRINT_ENV] = "fingerprint-1"
        events.append(("bind-fingerprint",))
        return "fingerprint-1"

    monkeypatch.setattr(structural, "bind_reference_structural_fingerprint", bind_fingerprint)

    def load_cache(values, *, asset_class, policy_version, requested_as_of):
        events.append(("load-cache", asset_class, policy_version, requested_as_of))
        return cache[0] if cache else None

    monkeypatch.setattr(structural, "load_structural_catalog", load_cache)

    def load_records(*, core, values, policy, timestamp, asset_class):
        events.append(("load-canonical", asset_class, timestamp))
        return raw

    monkeypatch.setattr(transaction, "_load_catalog_records", load_records)

    def merge_records(core, records, *, asset_class, timestamp):
        events.append(("merge-canonical", asset_class, timestamp, tuple(records)))
        return merged

    monkeypatch.setattr(transaction._bounded_lane, "_merge_certified_lane", merge_records)

    def publish_cache(
        values,
        *,
        asset_class,
        policy_version,
        source_as_of,
        raw_record_count,
        records,
    ):
        events.append(
            (
                "publish-cache",
                asset_class,
                policy_version,
                source_as_of,
                raw_record_count,
                tuple(records),
            )
        )
        cache.append(
            SimpleNamespace(
                records=tuple(records),
                raw_record_count=raw_record_count,
                source_as_of=source_as_of,
            )
        )
        return True

    monkeypatch.setattr(structural, "publish_structural_catalog", publish_cache)

    def forbidden_provider(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("structural prewarm must not perform provider preselection")

    monkeypatch.setattr(publication, "ensure_provider_preselection_publication", forbidden_provider)

    def forbidden_screening(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("structural prewarm must not perform terminal screening")

    base = SimpleNamespace(
        scheduled_discovery_lanes=lambda as_of: frozenset({asset_class})
        if as_of == timestamp
        else frozenset(),
    )
    monkeypatch.setattr(
        facade,
        "_core",
        SimpleNamespace(
            _base=base,
            build_bounded_terminal_preselection=forbidden_screening,
        ),
    )

    result = fanout.prepare_lane_structural_catalog(
        request_path,
        values={"RENDER": "true"},
        asset_class_value=asset_class.value,
        index=0,
    )

    assert result["structural_ready"] is True
    assert result["reused"] is False
    assert result["raw_record_count"] == 1
    assert result["record_count"] == 2
    assert result["provider_preselection_performed"] is False
    assert result["terminal_screening_performed"] is False
    assert result["structural_reconstruction_parallelized"] is False
    assert result["evidence_certified"] is False
    assert result["decision_authority"] is False
    assert result["execution_authority"] is False
    assert result["paper_only"] is True
    assert result["real_money_authorized"] is False
    assert [event[0] for event in events] == [
        "bind-fingerprint",
        "load-cache",
        "load-canonical",
        "merge-canonical",
        "publish-cache",
        "load-cache",
    ]


def _configure_cached_lane(monkeypatch, tmp_path):
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import comprehensive_market_discovery as facade
    from operations import transactional_comprehensive_discovery_lane as transaction

    asset_class = next(
        item
        for item in CandidateAssetClass
        if item not in {CandidateAssetClass.OTHER, CandidateAssetClass.OPTION}
    )
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")

    @dataclass(frozen=True)
    class Policy:
        provider_preselection_path: str | None = None
        version: str = "policy-v1"

    policy = Policy()
    timestamp = _epoch()
    source_as_of = timestamp - timedelta(minutes=1)
    merged = (SimpleNamespace(symbol="A"), SimpleNamespace(symbol="B"))
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, policy),
    )
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)

    def bind_fingerprint(values):
        values[structural._REFERENCE_STRUCTURAL_FINGERPRINT_ENV] = "fingerprint-1"
        events.append(("bind-fingerprint",))
        return "fingerprint-1"

    monkeypatch.setattr(structural, "bind_reference_structural_fingerprint", bind_fingerprint)
    monkeypatch.setattr(
        structural,
        "load_structural_catalog",
        lambda values, *, asset_class, policy_version, requested_as_of: (
            events.append(("load-cache", asset_class, policy_version, requested_as_of))
            or SimpleNamespace(records=merged, raw_record_count=2, source_as_of=source_as_of)
        ),
    )

    base = SimpleNamespace(
        _DEFAULT_REQUIRED_DISCOVERY_LANES=frozenset({asset_class}),
        _lane_is_scheduled=lambda lane, as_of: lane is asset_class and as_of == timestamp,
        scheduled_discovery_lanes=lambda as_of: frozenset({asset_class}),
    )

    def forbidden_screening(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("provider fan-out must never perform terminal screening")

    def forbidden_reconstruction(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("provider fan-out must never reconstruct structural catalogs")

    core = SimpleNamespace(
        _base=base,
        default_provider_preselection_market_probe=object(),
        build_bounded_terminal_preselection=forbidden_screening,
    )
    monkeypatch.setattr(facade, "_core", core)
    monkeypatch.setattr(transaction, "_load_catalog_records", forbidden_reconstruction)
    monkeypatch.setattr(transaction._bounded_lane, "_merge_certified_lane", forbidden_reconstruction)

    publication_path = tmp_path / "provider-preselection.json"
    monkeypatch.setattr(
        transaction,
        "_publication_path",
        lambda _directory, *, asset_class, index: publication_path,
    )
    return asset_class, request_path, timestamp, merged, events, publication_path


def test_lane_fanout_builds_and_promotes_clean_publication_without_screening_or_reconstruction(
    monkeypatch, tmp_path
) -> None:
    from operations import bounded_provider_preselection_publication as publication

    asset_class, request_path, timestamp, merged, events, publication_path = _configure_cached_lane(
        monkeypatch, tmp_path
    )
    observed = {}

    def fake_publication(catalogs, *, as_of, policy, market_probe):
        observed["catalogs"] = catalogs
        observed["as_of"] = as_of
        observed["policy"] = policy
        observed["market_probe"] = market_probe
        stage_path = Path(policy.provider_preselection_path)
        stage_path.write_text("{}", encoding="utf-8")
        events.append(("publication", stage_path))
        return SimpleNamespace(
            path=stage_path,
            catalog_count=2,
            reused=False,
            limitations=(),
        )

    monkeypatch.setattr(publication, "ensure_provider_preselection_publication", fake_publication)

    result = fanout.prepare_lane_provider_publication(
        request_path,
        values={"RENDER": "true"},
        asset_class_value=asset_class.value,
        index=2,
    )

    staging_path = publication_path.with_name(publication_path.name + ".fanout")
    assert result["publication_ready"] is True
    assert result["record_count"] == 2
    assert result["structural_reconstruction_parallelized"] is False
    assert result["limited_publication_promoted"] is False
    assert observed["as_of"] == timestamp
    assert observed["policy"].provider_preselection_path == str(staging_path)
    assert observed["catalogs"] == {asset_class: merged}
    assert publication_path.is_file()
    assert not staging_path.exists()
    assert events == [
        ("bind-fingerprint",),
        ("load-cache", asset_class, "policy-v1", timestamp),
        ("publication", staging_path),
    ]


def test_lane_fanout_discards_limited_publication_for_serial_retry(monkeypatch, tmp_path) -> None:
    from operations import bounded_provider_preselection_publication as publication

    asset_class, request_path, _timestamp, _merged, _events, publication_path = _configure_cached_lane(
        monkeypatch, tmp_path
    )

    def limited_publication(catalogs, *, as_of, policy, market_probe):
        stage_path = Path(policy.provider_preselection_path)
        stage_path.write_text("limited", encoding="utf-8")
        return SimpleNamespace(
            path=stage_path,
            catalog_count=2,
            reused=False,
            limitations=("provider throttled",),
        )

    monkeypatch.setattr(publication, "ensure_provider_preselection_publication", limited_publication)

    with pytest.raises(RuntimeError, match="produced limited evidence"):
        fanout.prepare_lane_provider_publication(
            request_path,
            values={"RENDER": "true"},
            asset_class_value=asset_class.value,
            index=2,
        )

    staging_path = publication_path.with_name(publication_path.name + ".fanout")
    assert not publication_path.exists()
    assert not staging_path.exists()


def test_lane_fanout_cache_miss_falls_back_without_reconstruction(monkeypatch, tmp_path) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import comprehensive_market_discovery as facade
    from operations import transactional_comprehensive_discovery_lane as transaction

    asset_class = next(
        item
        for item in CandidateAssetClass
        if item not in {CandidateAssetClass.OTHER, CandidateAssetClass.OPTION}
    )
    timestamp = _epoch()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    policy = SimpleNamespace(version="policy-v1")

    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, policy),
    )
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)
    monkeypatch.setattr(
        structural,
        "bind_reference_structural_fingerprint",
        lambda values: values.__setitem__(structural._REFERENCE_STRUCTURAL_FINGERPRINT_ENV, "fp") or "fp",
    )
    monkeypatch.setattr(structural, "load_structural_catalog", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        facade,
        "_core",
        SimpleNamespace(_base=SimpleNamespace(scheduled_discovery_lanes=lambda _as_of: frozenset({asset_class}))),
    )

    def forbidden_reconstruction(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("cache miss must fall back to later serialized reconstruction")

    monkeypatch.setattr(transaction, "_load_catalog_records", forbidden_reconstruction)
    monkeypatch.setattr(transaction._bounded_lane, "_merge_certified_lane", forbidden_reconstruction)

    with pytest.raises(RuntimeError, match="requires prewarmed structural cache"):
        fanout.prepare_lane_provider_publication(
            request_path,
            values={"RENDER": "true"},
            asset_class_value=asset_class.value,
            index=0,
        )


def test_runtime_wrapper_runs_acceleration_before_canonical_builder(monkeypatch, tmp_path) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    events: list[tuple[object, ...]] = []
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    timestamp = _epoch()

    def canonical(path, *, values=None):
        events.append(("canonical", Path(path), dict(values or {})))
        return Path(path).with_name("manifest.json")

    monkeypatch.setattr(spawn_safe, "build_spool", canonical)
    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, object()),
    )
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)
    monkeypatch.setattr(
        fanout,
        "run_provider_acquisition_fanout",
        lambda path, *, values, decision_epoch: events.append(
            ("fanout", Path(path), decision_epoch, dict(values))
        )
        or {},
    )

    fanout.install_epoch_scoped_provider_acquisition()
    wrapped = spawn_safe.build_spool
    assert getattr(wrapped, "_epoch_scoped_provider_acquisition", False) is True

    result = wrapped(request_path, values={"RENDER": "true", "X": "1"})

    assert result == request_path.with_name("manifest.json")
    assert events[0][:3] == ("fanout", request_path, timestamp)
    assert events[1][:2] == ("canonical", request_path)
    assert events[0][3]["X"] == "1"
    assert events[1][2]["X"] == "1"
