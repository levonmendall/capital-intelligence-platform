from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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


def test_provider_fanout_is_bounded_and_overlaps(monkeypatch, tmp_path) -> None:
    lanes = tuple(
        item
        for item in CandidateAssetClass
        if item is not CandidateAssetClass.OTHER
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
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(command, **kwargs):
        process = FakeProcess(10_000 + len(created))
        created.append((tuple(command), dict(kwargs), process))
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

    assert len(created) == 5
    assert report["completed"] == 5
    assert report["failed"] == 0
    assert report["maximum_parallel"] == 3
    assert report["worker_limit"] == 3
    assert report["evidence_certified"] is False
    assert report["decision_authority"] is False
    assert report["execution_authority"] is False
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False
    assert all(item[1]["start_new_session"] is (fanout.os.name == "posix") for item in created)


def test_provider_fanout_preserves_downstream_epoch_reserve(monkeypatch) -> None:
    from operations import continuous_evidence_plane as plane

    monkeypatch.setattr(plane, "_max_age_seconds", lambda _values: 900.0)
    epoch = _epoch()

    # With 800 seconds left, the fan-out is capped at five minutes and leaves at least
    # eight minutes for serialized screening, paper evidence, and finalization.
    assert fanout._fanout_budget_seconds(
        epoch,
        {},
        now=epoch + timedelta(seconds=100),
    ) == 300.0

    # Once only the downstream reserve remains, provider fan-out refuses to consume it.
    assert fanout._fanout_budget_seconds(
        epoch,
        {},
        now=epoch + timedelta(seconds=500),
    ) == 0.0


def test_lane_fanout_builds_canonical_publication_without_screening(monkeypatch, tmp_path) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import bounded_provider_preselection_publication as publication
    from operations import cached_transactional_comprehensive_discovery_lane as cached
    from operations import comprehensive_discovery_input_spool as legacy
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

    policy = Policy()
    timestamp = _epoch()
    merged = (SimpleNamespace(symbol="A"), SimpleNamespace(symbol="B"))
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(bounded, "_validate_request", lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, policy))
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)
    monkeypatch.setattr(cached, "install_cached_structural_lane_loader", lambda: events.append(("install-cache",)))

    base = SimpleNamespace(
        _DEFAULT_REQUIRED_DISCOVERY_LANES=frozenset({asset_class}),
        _lane_is_scheduled=lambda lane, as_of: lane is asset_class and as_of == timestamp,
    )

    def forbidden_screening(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("provider fan-out must never perform terminal screening")

    core = SimpleNamespace(
        _base=base,
        default_provider_preselection_market_probe=object(),
        build_bounded_terminal_preselection=forbidden_screening,
    )
    monkeypatch.setattr(facade, "_core", core)
    monkeypatch.setattr(
        transaction,
        "_load_catalog_records",
        lambda **kwargs: events.append(("load", kwargs["asset_class"], kwargs["timestamp"])) or (object(),),
    )
    monkeypatch.setattr(
        transaction._bounded_lane,
        "_merge_certified_lane",
        lambda _core, _raw, *, asset_class, timestamp: events.append(("merge", asset_class, timestamp)) or merged,
    )
    publication_path = tmp_path / "provider-preselection.json"
    monkeypatch.setattr(
        transaction,
        "_publication_path",
        lambda _directory, *, asset_class, index: publication_path,
    )

    observed = {}

    def fake_publication(catalogs, *, as_of, policy, market_probe):
        observed["catalogs"] = catalogs
        observed["as_of"] = as_of
        observed["policy"] = policy
        observed["market_probe"] = market_probe
        events.append(("publication",))
        return SimpleNamespace(catalog_count=2, reused=False)

    monkeypatch.setattr(publication, "ensure_provider_preselection_publication", fake_publication)

    result = fanout.prepare_lane_provider_publication(
        request_path,
        values={"RENDER": "true"},
        asset_class_value=asset_class.value,
        index=2,
    )

    assert result["publication_ready"] is True
    assert result["record_count"] == 2
    assert observed["as_of"] == timestamp
    assert observed["policy"].provider_preselection_path == str(publication_path)
    assert observed["catalogs"] == {asset_class: merged}
    assert events == [
        ("install-cache",),
        ("load", asset_class, timestamp),
        ("merge", asset_class, timestamp),
        ("publication",),
    ]


def test_runtime_wrapper_runs_fanout_before_canonical_builder(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setattr(legacy, "_load_request", lambda _path: {"decision_epoch": timestamp.isoformat()})
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)
    monkeypatch.setattr(
        fanout,
        "run_provider_acquisition_fanout",
        lambda path, *, values, decision_epoch: events.append(("fanout", Path(path), decision_epoch, dict(values))) or {},
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
