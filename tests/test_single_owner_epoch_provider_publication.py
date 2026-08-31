from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations import cached_transactional_comprehensive_discovery_lane as cached_lane
from operations import comprehensive_discovery_structural_prewarm as overlap


def _as_of() -> datetime:
    return datetime(2026, 8, 28, 15, 27, tzinfo=timezone.utc)


def test_us_equity_overlap_uses_exact_comprehensive_request_identity(monkeypatch, tmp_path) -> None:
    from operations import comprehensive_discovery_input_spool as spool
    from operations import comprehensive_market_discovery as facade
    from operations import evidence_state_scope as state_scope
    from operations import epoch_scoped_provider_acquisition as acquisition

    policy = SimpleNamespace(version="policy-v1")
    request_path = tmp_path / "request.json"
    observed: dict[str, object] = {}

    monkeypatch.setattr(overlap, "_eligible", lambda values: True)
    monkeypatch.setattr(
        facade,
        "_core",
        SimpleNamespace(ComprehensiveMarketDiscoveryPolicy=lambda: policy),
    )
    monkeypatch.setattr(
        state_scope,
        "load_evidence_state_scope",
        lambda *, as_of, values: SimpleNamespace(
            held_symbols=("HELD",),
            tracked_symbols=("TRACKED",),
        ),
    )

    def fake_prepare_request(**kwargs):
        observed["request"] = kwargs
        return SimpleNamespace(path=request_path)

    def fake_fanout(path, *, values, decision_epoch):
        observed["fanout_path"] = Path(path)
        observed["fanout_values"] = dict(values)
        observed["fanout_epoch"] = decision_epoch
        return {"attempted": True, "completed": 5, "failed": 0}

    monkeypatch.setattr(spool, "prepare_request", fake_prepare_request)
    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }
    result = overlap.prewarm_epoch_provider_inputs(
        evidence_as_of=_as_of(),
        values=values,
    )

    request = observed["request"]
    assert request["values"] == values
    assert request["decision_epoch"] == _as_of()
    assert request["held_symbols"] == ("HELD",)
    assert request["tracked_symbols"] == ("TRACKED",)
    # The stage-owned comprehensive call uses its default empty exclusion set and policy.
    assert request["excluded_symbols"] == ()
    assert request["policy"] is policy
    assert observed["fanout_path"] == request_path
    assert observed["fanout_values"] == values
    assert observed["fanout_epoch"] == _as_of()
    assert result == {"attempted": True, "completed": 5, "failed": 0}


def test_overlap_handle_finishes_only_inside_original_absolute_budget(monkeypatch) -> None:
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(overlap.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(overlap.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.wait_timeouts: list[float | None] = []
            self.terminated = False
            self.killed = False

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_timeouts.append(timeout)
            if self.returncode is not None:
                return self.returncode
            if timeout is not None and timeout > 1.0:
                clock.now += float(timeout)
                raise subprocess.TimeoutExpired("overlap-sidecar", timeout)
            self.returncode = -15 if self.terminated else -9
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

    process = FakeProcess()
    handle = overlap.StructuralPrewarmHandle(
        process=process,
        deadline_monotonic=105.0,
    )

    handle.finish()

    assert process.wait_timeouts[0] == 5.0
    assert process.terminated is True
    assert process.killed is False
    assert handle.process is None


def test_us_equity_stage_runs_overlap_sidecar_through_snapshot_reuse(monkeypatch) -> None:
    import run_stage_isolated_evidence_stage as stage_runtime
    from operations import evidence_preparation_progress as progress
    from operations import evidence_state_scope as state_scope
    from operations import equity_discovery_snapshot as equity_snapshot

    events: list[str] = []
    scope = SimpleNamespace(held_symbols=("H",), tracked_symbols=("T",))
    snapshot = SimpleNamespace(
        snapshot_id="equity-snapshot",
        held_symbols=scope.held_symbols,
        tracked_symbols=scope.tracked_symbols,
        excluded_symbols=("BASE",),
    )

    class Handle:
        def finish(self):
            events.append("finish-overlap")

    monkeypatch.setattr(
        overlap,
        "start_render_structural_prewarm",
        lambda **kwargs: events.append("start-overlap") or Handle(),
    )
    monkeypatch.setattr(progress, "install_post_public_provider_progress", lambda values: None)
    monkeypatch.setattr(
        state_scope,
        "load_evidence_state_scope",
        lambda *, as_of, values: events.append("load-scope") or scope,
    )
    monkeypatch.setattr(
        equity_snapshot,
        "load_equity_discovery_snapshot",
        lambda *, evidence_as_of, values: events.append("load-snapshot") or snapshot,
    )
    monkeypatch.setattr(stage_runtime, "_base_universe_symbols", lambda: ("BASE",))
    # The stage runner intentionally binds reference identity into process-global env for
    # its finite child lifetime. Register the same keys with monkeypatch first so this unit
    # test restores them at teardown and cannot poison unrelated discovery tests.
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID", "reference-1")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH", "/tmp/reference.json")

    state = SimpleNamespace(
        evidence_as_of=_as_of(),
        reference_manifest_id="reference-1",
        reference_manifest_path="/tmp/reference.json",
    )
    result = stage_runtime._stage_us_equity_discovery(
        {"RENDER": "true"},
        state,
    )

    assert result == {"snapshot_id": "equity-snapshot", "reused": True}
    assert events == ["start-overlap", "load-scope", "load-snapshot", "finish-overlap"]


def test_transactional_publication_reuses_valid_epoch_artifact_without_network(monkeypatch, tmp_path) -> None:
    publication = cached_lane._canonical._publication
    expected = SimpleNamespace(
        path=tmp_path / "provider.json",
        catalog_count=1,
        limitations=(),
        reused=True,
    )

    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication._core, "_publication_path", lambda policy: expected.path)
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: expected)

    result = cached_lane._reuse_only_provider_preselection_publication(
        {"lane": (object(),)},
        as_of=_as_of(),
        policy=SimpleNamespace(preselection_freshness_days=3),
        market_probe=lambda *args: (_ for _ in ()).throw(
            AssertionError("reuse-only publication must never call a provider")
        ),
    )

    assert result is expected


def test_transactional_publication_missing_artifact_fails_without_network(monkeypatch, tmp_path) -> None:
    publication = cached_lane._canonical._publication

    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication._core, "_publication_path", lambda policy: tmp_path / "missing.json")
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: None)

    with pytest.raises(
        publication.ProviderPreselectionPublicationError,
        match="refuses late provider reacquisition",
    ):
        cached_lane._reuse_only_provider_preselection_publication(
            {"lane": (object(),)},
            as_of=_as_of(),
            policy=SimpleNamespace(preselection_freshness_days=3),
            market_probe=lambda *args: (_ for _ in ()).throw(
                AssertionError("missing early publication must fail, not reacquire")
            ),
        )


def test_transactional_publication_rejects_limited_epoch_artifact(monkeypatch, tmp_path) -> None:
    publication = cached_lane._canonical._publication
    limited = SimpleNamespace(
        path=tmp_path / "provider.json",
        catalog_count=1,
        limitations=("provider degraded",),
        reused=True,
    )

    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication._core, "_publication_path", lambda policy: limited.path)
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: limited)

    with pytest.raises(
        publication.ProviderPreselectionPublicationError,
        match="refuses degraded provider evidence",
    ):
        cached_lane._reuse_only_provider_preselection_publication(
            {"lane": (object(),)},
            as_of=_as_of(),
            policy=SimpleNamespace(preselection_freshness_days=3),
        )


def _configure_reuse_only_lane(monkeypatch, tmp_path, *, existing):
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import bounded_provider_preselection_publication as publication
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import comprehensive_market_discovery as facade
    from operations import epoch_scoped_provider_acquisition as acquisition
    from operations import transactional_comprehensive_discovery_lane as transaction

    asset_class = next(
        item
        for item in acquisition.CandidateAssetClass
        if item not in {acquisition.CandidateAssetClass.OTHER, acquisition.CandidateAssetClass.OPTION}
    )
    timestamp = _as_of()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    policy = facade._core.ComprehensiveMarketDiscoveryPolicy()
    records = (SimpleNamespace(symbol="A"),)
    canonical_path = tmp_path / "provider.json"

    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, policy),
    )
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)
    monkeypatch.setattr(structural, "bind_reference_structural_fingerprint", lambda values: "fp")
    monkeypatch.setattr(
        structural,
        "load_structural_catalog",
        lambda *args, **kwargs: SimpleNamespace(records=records, source_as_of=timestamp),
    )
    base = SimpleNamespace(
        _DEFAULT_REQUIRED_DISCOVERY_LANES=frozenset({asset_class}),
        scheduled_discovery_lanes=lambda _as_of: frozenset({asset_class}),
        _lane_is_scheduled=lambda _asset_class, _as_of: True,
    )
    monkeypatch.setattr(
        facade,
        "_core",
        SimpleNamespace(
            _base=base,
            default_provider_preselection_market_probe=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("reuse-only fanout must never call the provider")
            ),
        ),
    )
    monkeypatch.setattr(
        transaction,
        "_publication_path",
        lambda _directory, *, asset_class, index: canonical_path,
    )
    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: records)
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(
        publication._core,
        "_publication_path",
        lambda policy: Path(policy.provider_preselection_path),
    )
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: existing)
    monkeypatch.setattr(
        publication,
        "ensure_provider_preselection_publication",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reuse-only fanout must never reacquire provider evidence")
        ),
    )
    return acquisition, asset_class, request_path, timestamp, records, canonical_path


def test_comprehensive_fanout_reuses_clean_publication_without_network(monkeypatch, tmp_path) -> None:
    expected = SimpleNamespace(
        path=tmp_path / "provider.json",
        catalog_count=1,
        limitations=(),
        reused=True,
    )
    acquisition, asset_class, request_path, _timestamp, records, _path = _configure_reuse_only_lane(
        monkeypatch,
        tmp_path,
        existing=expected,
    )

    result = acquisition.prepare_lane_provider_publication(
        request_path,
        values={"RENDER": "true", acquisition._REUSE_ONLY_ENV: "true"},
        asset_class_value=asset_class.value,
        index=0,
    )

    assert result["publication_ready"] is True
    assert result["record_count"] == len(records)
    assert result["reused"] is True


def test_comprehensive_fanout_missing_publication_fails_without_network(monkeypatch, tmp_path) -> None:
    acquisition, asset_class, request_path, _timestamp, _records, _path = _configure_reuse_only_lane(
        monkeypatch,
        tmp_path,
        existing=None,
    )

    with pytest.raises(RuntimeError, match="refuses provider reacquisition"):
        acquisition.prepare_lane_provider_publication(
            request_path,
            values={"RENDER": "true", acquisition._REUSE_ONLY_ENV: "true"},
            asset_class_value=asset_class.value,
            index=0,
        )


def test_runtime_wrapper_marks_comprehensive_handoff_reuse_only(monkeypatch, tmp_path) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import epoch_scoped_provider_acquisition as acquisition
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    timestamp = _as_of()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    observed: dict[str, object] = {"validations": []}
    lanes = ((0, acquisition.CandidateAssetClass.US_EQUITY),)

    def canonical(path, *, values=None):
        observed["canonical_values"] = dict(values or {})
        return Path(path).with_name("manifest.json")

    monkeypatch.setattr(spawn_safe, "build_spool", canonical)
    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda _path, _values: ({"decision_epoch": timestamp.isoformat()}, object()),
    )
    monkeypatch.setattr(legacy, "_parse_timestamp", lambda _value, field_name: timestamp)
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)
    monkeypatch.setattr(
        acquisition,
        "run_provider_acquisition_fanout",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime handoff must not start budgeted provider fanout")
        ),
    )

    def validate(path, *, values, asset_class_value, index):
        observed["validations"].append(
            (Path(path), dict(values), str(asset_class_value), int(index))
        )
        return {"publication_ready": True, "reused": True}

    monkeypatch.setattr(acquisition, "prepare_lane_provider_publication", validate)
    acquisition.install_epoch_scoped_provider_acquisition()

    result = spawn_safe.build_spool(request_path, values={"RENDER": "true", "X": "1"})

    assert result == request_path.with_name("manifest.json")
    assert observed["validations"] == [
        (
            request_path,
            {
                "RENDER": "true",
                "X": "1",
                acquisition._REUSE_ONLY_ENV: "true",
            },
            acquisition.CandidateAssetClass.US_EQUITY.value,
            0,
        )
    ]
    assert acquisition._REUSE_ONLY_ENV not in observed["canonical_values"]
    assert observed["canonical_values"]["X"] == "1"


def test_existing_epoch_budget_and_authority_bounds_are_unchanged() -> None:
    from operations import epoch_scoped_provider_acquisition as acquisition

    assert acquisition._MAX_FANOUT_SECONDS == 300.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0
    assert acquisition._DEFAULT_WORKERS == 6
    assert acquisition._MAX_WORKERS == 6
