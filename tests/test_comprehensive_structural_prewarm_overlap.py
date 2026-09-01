from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_prewarm as prewarm
from operations import evidence_preparation_progress as progress


def _as_of() -> datetime:
    return datetime(2026, 8, 28, 15, 27, tzinfo=timezone.utc)


def test_non_render_structural_prewarm_never_spawns(monkeypatch) -> None:
    def unexpected_popen(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("non-Render structural prewarm must not spawn")

    monkeypatch.setattr(prewarm.subprocess, "Popen", unexpected_popen)
    handle = prewarm.start_render_structural_prewarm(
        evidence_as_of=_as_of(),
        values={"RENDER": "false"},
    )

    assert handle.process is None


def test_render_structural_prewarm_stays_in_stage_process_group(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}
    fake_process = SimpleNamespace(poll=lambda: 0)

    def fake_popen(command, **kwargs):
        observed["command"] = tuple(command)
        observed.update(kwargs)
        return fake_process

    # Cache reclamation is covered independently. This test owns only the sidecar's process
    # group contract, so isolate the pre-launch handoff before monkeypatching subprocess.Popen.
    monkeypatch.setattr(prewarm, "_release_pre_us_equity_file_cache", lambda values: None)
    monkeypatch.setattr(prewarm.subprocess, "Popen", fake_popen)
    handle = prewarm.start_render_structural_prewarm(
        evidence_as_of=_as_of(),
        values={
            "RENDER": "true",
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            prewarm._REFERENCE_MANIFEST_ID_ENV: "manifest-1",
            prewarm._REFERENCE_MANIFEST_PATH_ENV: str(tmp_path / "manifest.json"),
        },
    )

    assert handle.process is fake_process
    assert observed["start_new_session"] is False
    assert "operations.comprehensive_discovery_structural_prewarm" in observed["command"]


def test_structural_prewarm_builds_only_scheduled_non_option_structure(monkeypatch) -> None:
    from operations import bounded_lane_comprehensive_discovery_worker as bounded_lane
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import transactional_comprehensive_discovery_lane as canonical
    from operations import comprehensive_market_discovery as facade
    from operations import evidence_file_cache_release as cache_release

    events: list[tuple[object, ...]] = []
    base = SimpleNamespace(
        scheduled_discovery_lanes=lambda timestamp: frozenset(
            {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION}
        )
    )
    core = SimpleNamespace(
        _base=base,
        ComprehensiveMarketDiscoveryPolicy=lambda: SimpleNamespace(version="policy-v1"),
    )

    monkeypatch.setattr(prewarm, "_eligible", lambda values: True)
    monkeypatch.setattr(facade, "_core", core)
    monkeypatch.setattr(
        lane_local,
        "_candidate_lanes",
        lambda: (CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION),
    )
    monkeypatch.setattr(
        structural,
        "bind_reference_structural_fingerprint",
        lambda values: events.append(("bind",)) or "fingerprint",
    )
    monkeypatch.setattr(structural, "load_structural_catalog", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        canonical,
        "_load_catalog_records",
        lambda **kwargs: events.append(("load", kwargs["asset_class"])) or ("raw",),
    )
    monkeypatch.setattr(
        bounded_lane,
        "_merge_certified_lane",
        lambda core, raw, *, asset_class, timestamp: events.append(("merge", asset_class))
        or ("merged",),
    )
    monkeypatch.setattr(
        structural,
        "publish_structural_catalog",
        lambda values, **kwargs: events.append(("publish", kwargs["asset_class"])) or True,
    )
    monkeypatch.setattr(
        cache_release,
        "release_current_reference_file_cache",
        lambda values: events.append(("release",)),
    )

    count = prewarm.prewarm_structural_catalogs(
        evidence_as_of=_as_of(),
        values={"RENDER": "true"},
    )

    assert count == 1
    assert ("load", CandidateAssetClass.FUTURE) in events
    assert ("merge", CandidateAssetClass.FUTURE) in events
    assert ("publish", CandidateAssetClass.FUTURE) in events
    assert not any(
        event[0] in {"load", "merge", "publish"}
        and len(event) > 1
        and event[1] is CandidateAssetClass.OPTION
        for event in events
    )


def test_progress_hook_starts_overlap_only_for_active_render_us_equity_stage(monkeypatch) -> None:
    from operations import comprehensive_discovery_structural_prewarm as structural_prewarm
    from operations import stage_isolated_evidence_pipeline as stage_state

    registered: list[object] = []
    calls: list[tuple[datetime, dict[str, str]]] = []
    fake_process = object()
    fake_handle = SimpleNamespace(process=fake_process, stop=lambda: None)

    monkeypatch.setattr(progress, "_STRUCTURAL_PREWARM_STARTED", False)
    monkeypatch.setattr(
        stage_state,
        "load_stage_isolated_evidence_state",
        lambda values: SimpleNamespace(
            state="running",
            current_stage="us_equity_discovery",
            evidence_as_of=_as_of(),
        ),
    )
    monkeypatch.setattr(
        structural_prewarm,
        "start_render_structural_prewarm",
        lambda *, evidence_as_of, values: calls.append((evidence_as_of, dict(values)))
        or fake_handle,
    )
    monkeypatch.setattr(progress.atexit, "register", lambda callback: registered.append(callback))

    progress._start_us_equity_structural_prewarm({"RENDER": "true"})

    assert calls == [(_as_of(), {"RENDER": "true"})]
    assert registered == [fake_handle.stop]
    assert progress._STRUCTURAL_PREWARM_STARTED is True


def test_progress_hook_does_not_overlap_during_paper_stage(monkeypatch) -> None:
    from operations import comprehensive_discovery_structural_prewarm as structural_prewarm
    from operations import stage_isolated_evidence_pipeline as stage_state

    monkeypatch.setattr(progress, "_STRUCTURAL_PREWARM_STARTED", False)
    monkeypatch.setattr(
        stage_state,
        "load_stage_isolated_evidence_state",
        lambda values: SimpleNamespace(
            state="running",
            current_stage="paper_evidence",
            evidence_as_of=_as_of(),
        ),
    )
    monkeypatch.setattr(
        structural_prewarm,
        "start_render_structural_prewarm",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("paper evidence must not start structural overlap")
        ),
    )

    progress._start_us_equity_structural_prewarm({"RENDER": "true"})

    assert progress._STRUCTURAL_PREWARM_STARTED is False
