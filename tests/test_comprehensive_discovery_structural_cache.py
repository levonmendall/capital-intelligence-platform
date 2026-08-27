from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import cached_transactional_comprehensive_discovery_lane as cached_lane
from operations import comprehensive_discovery_structural_cache as structural
from operations import reference_readiness as reference
from operations import transactional_comprehensive_discovery_lane as canonical_lane
import run_dag_native_continuous_evidence_plane as dag_runtime


def _write_reference_manifest(
    tmp_path,
    *,
    name: str = "manifest-1.json",
    captured_at: str = "2026-08-27T04:00:00+00:00",
    bound_at: str = "2026-08-27T04:01:00+00:00",
    component_id: str = "component-1",
    catalog_symbol: str = "EURUSD",
    config_fingerprint: str = "config-1",
):
    material = {
        "schema_version": reference._SCHEMA_VERSION,
        "release": "release-1",
        "captured_at": captured_at,
        "bound_at": bound_at,
        "config_fingerprint": config_fingerprint,
        "eodhd_exchanges": ["US"],
        "futures_roots": ["ES"],
        "active_lanes": [CandidateAssetClass.FX.value],
        "component_ids": {"catalog": component_id},
        "component_captured_at": {"catalog": captured_at},
        "catalogs": {
            CandidateAssetClass.FX.value: [
                {
                    "symbol": catalog_symbol,
                    "provider_symbol": catalog_symbol,
                }
            ]
        },
        "paper_only": True,
        "real_money_authorized": False,
    }
    manifest_id = reference._fingerprint(material)
    path = tmp_path / name
    path.write_text(
        json.dumps({**material, "manifest_id": manifest_id}, sort_keys=True),
        encoding="utf-8",
    )
    return path, manifest_id


def _values(tmp_path):
    path, manifest_id = _write_reference_manifest(tmp_path)
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-1",
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID": manifest_id,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH": str(path),
    }
    structural.bind_reference_structural_fingerprint(values)
    return values


def _core_with_schedule(*, active: bool = True):
    lanes = (CandidateAssetClass.FX,) if active else ()
    return SimpleNamespace(
        _base=SimpleNamespace(scheduled_discovery_lanes=lambda _timestamp: lanes)
    )


def test_structural_cache_reuses_same_certified_content_across_fresh_manifests(tmp_path) -> None:
    path_1, manifest_1 = _write_reference_manifest(tmp_path, name="manifest-1.json")
    path_2, manifest_2 = _write_reference_manifest(
        tmp_path,
        name="manifest-2.json",
        captured_at="2026-08-27T05:00:00+00:00",
        bound_at="2026-08-27T05:01:00+00:00",
        component_id="component-2",
    )
    assert manifest_1 != manifest_2

    values_1 = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-1",
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID": manifest_1,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH": str(path_1),
    }
    values_2 = {
        **values_1,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID": manifest_2,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH": str(path_2),
    }
    fingerprint_1 = structural.bind_reference_structural_fingerprint(values_1)
    fingerprint_2 = structural.bind_reference_structural_fingerprint(values_2)
    assert fingerprint_1 == fingerprint_2

    source = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)
    records = ("A", "B")
    assert structural.publish_structural_catalog(
        values_1,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        source_as_of=source,
        raw_record_count=1,
        records=records,
    )

    loaded = structural.load_structural_catalog(
        values_2,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        requested_as_of=source + timedelta(minutes=20),
    )
    assert loaded is not None
    assert loaded.records == records
    assert loaded.raw_record_count == 1
    assert loaded.source_as_of == source

    assert structural.load_structural_catalog(
        values_2,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-2",
        requested_as_of=source + timedelta(minutes=20),
    ) is None
    assert structural.load_structural_catalog(
        {**values_2, "CAPITAL_INTELLIGENCE_RELEASE": "release-2"},
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        requested_as_of=source + timedelta(minutes=20),
    ) is None


def test_structural_cache_misses_when_certified_structure_changes(tmp_path) -> None:
    path_1, manifest_1 = _write_reference_manifest(tmp_path, name="stable.json")
    path_2, manifest_2 = _write_reference_manifest(
        tmp_path,
        name="changed.json",
        catalog_symbol="GBPUSD",
    )
    values_1 = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-1",
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID": manifest_1,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH": str(path_1),
    }
    values_2 = {
        **values_1,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID": manifest_2,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH": str(path_2),
    }
    assert structural.bind_reference_structural_fingerprint(values_1) != structural.bind_reference_structural_fingerprint(values_2)

    source = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)
    assert structural.publish_structural_catalog(
        values_1,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        source_as_of=source,
        raw_record_count=1,
        records=("A",),
    )
    assert structural.load_structural_catalog(
        values_2,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        requested_as_of=source + timedelta(minutes=20),
    ) is None


def test_structural_fingerprint_rejects_tampered_manifest(tmp_path) -> None:
    path, manifest_id = _write_reference_manifest(tmp_path, name="tampered.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["catalogs"][CandidateAssetClass.FX.value][0]["symbol"] = "TAMPERED"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-1",
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID": manifest_id,
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH": str(path),
    }
    with pytest.raises(reference.ReferenceReadinessError, match="integrity check failed"):
        structural.reference_structural_fingerprint(values)


def test_structural_cache_never_relabels_future_or_option_structure(tmp_path) -> None:
    values = _values(tmp_path)
    source = datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc)
    assert structural.publish_structural_catalog(
        values,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        source_as_of=source,
        raw_record_count=1,
        records=("A",),
    )
    assert structural.load_structural_catalog(
        values,
        asset_class=CandidateAssetClass.FX,
        policy_version="policy-1",
        requested_as_of=source - timedelta(seconds=1),
    ) is None
    assert structural.publish_structural_catalog(
        values,
        asset_class=CandidateAssetClass.OPTION,
        policy_version="policy-1",
        source_as_of=source,
        raw_record_count=1,
        records=("OPT",),
    ) is False


def test_cached_lane_reuses_merged_structure_but_not_epoch_work(monkeypatch, tmp_path) -> None:
    values = _values(tmp_path)
    timestamp = datetime(2026, 8, 27, 5, 20, tzinfo=timezone.utc)
    entry = structural.StructuralCatalogCacheEntry(
        records=("merged-a", "merged-b"),
        raw_record_count=1,
        source_as_of=timestamp - timedelta(minutes=20),
    )
    monkeypatch.setattr(structural, "load_structural_catalog", lambda *args, **kwargs: entry)
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_LOAD_CATALOG_RECORDS",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("canonical structural load ran")),
    )
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_MERGE_CERTIFIED_LANE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("canonical merge ran")),
    )

    raw = cached_lane._load_catalog_records(
        core=_core_with_schedule(active=True),
        values=values,
        policy=SimpleNamespace(version="policy-1"),
        timestamp=timestamp,
        asset_class=CandidateAssetClass.FX,
    )
    assert len(raw) == 1
    assert tuple(raw) == ("merged-a", "merged-b")
    merged = cached_lane._merge_certified_lane(
        object(), raw, asset_class=CandidateAssetClass.FX, timestamp=timestamp
    )
    assert merged == ("merged-a", "merged-b")

    source = inspect.getsource(cached_lane)
    assert "_canonical._load_catalog_records = _load_catalog_records" in source
    assert "_canonical._bounded_lane._merge_certified_lane = _merge_certified_lane" in source
    # Screening may be wrapped for non-authoritative progress instrumentation, but it must
    # still execute the canonical current-epoch implementation rather than being cached.
    assert "_canonical._build_deep_lane = _build_deep_lane" in source
    assert "return _ORIGINAL_BUILD_DEEP_LANE(*args, **kwargs)" in source
    assert '_record_watchdog_phase("screening-lane")' in source
    assert "ensure_provider_preselection_publication" not in source
    assert "default_redundant_market_probe" not in source


def test_schedule_change_rejects_structural_reuse(monkeypatch, tmp_path) -> None:
    values = _values(tmp_path)
    timestamp = datetime(2026, 8, 27, 5, 20, tzinfo=timezone.utc)
    entry = structural.StructuralCatalogCacheEntry(
        records=("cached",),
        raw_record_count=1,
        source_as_of=timestamp - timedelta(minutes=20),
    )
    monkeypatch.setattr(structural, "load_structural_catalog", lambda *args, **kwargs: entry)
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_LOAD_CATALOG_RECORDS",
        lambda **kwargs: ("fresh",),
    )
    core = SimpleNamespace(
        _base=SimpleNamespace(
            scheduled_discovery_lanes=lambda when: (
                (CandidateAssetClass.FX,)
                if when == timestamp
                else ()
            )
        )
    )

    raw = cached_lane._load_catalog_records(
        core=core,
        values=values,
        policy=SimpleNamespace(version="policy-1"),
        timestamp=timestamp,
        asset_class=CandidateAssetClass.FX,
    )
    assert raw == ("fresh",)


def test_cache_miss_runs_canonical_structure_and_write_is_advisory(monkeypatch, tmp_path) -> None:
    values = _values(tmp_path)
    timestamp = datetime(2026, 8, 27, 5, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(structural, "load_structural_catalog", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_LOAD_CATALOG_RECORDS",
        lambda **kwargs: ("raw-record",),
    )
    monkeypatch.setattr(
        cached_lane,
        "_ORIGINAL_MERGE_CERTIFIED_LANE",
        lambda *args, **kwargs: ("merged-record",),
    )
    monkeypatch.setattr(
        structural,
        "publish_structural_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("advisory cache write")),
    )

    raw = cached_lane._load_catalog_records(
        core=_core_with_schedule(active=True),
        values=values,
        policy=SimpleNamespace(version="policy-1"),
        timestamp=timestamp,
        asset_class=CandidateAssetClass.FX,
    )
    assert raw == ("raw-record",)
    merged = cached_lane._merge_certified_lane(
        object(), raw, asset_class=CandidateAssetClass.FX, timestamp=timestamp
    )
    assert merged == ("merged-record",)


def test_runtime_routes_only_transaction_child_through_structural_cache(monkeypatch) -> None:
    from operations import authoritative_comprehensive_discovery as authoritative
    from operations import component_qualified_evidence_maintenance as maintenance
    from operations import persistent_certification_scheduler as scheduler
    from operations import transactional_lane_comprehensive_discovery_coordinator as coordinator

    monkeypatch.setattr(dag_runtime, "install_comprehensive_discovery_runtime_contract", lambda: None)
    progress = __import__(
        "operations.evidence_preparation_progress",
        fromlist=["install_post_public_provider_progress"],
    )
    monkeypatch.setattr(progress, "install_post_public_provider_progress", lambda: None)
    monkeypatch.setattr(
        maintenance._supervised_discovery_runner,
        "_dag_native_supervision",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        scheduler.PersistentCertificationScheduler.run,
        "_dag_native_supervision",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        authoritative._acquire,
        "_spawn_safe_authoritative_acquisition",
        True,
        raising=False,
    )
    monkeypatch.setattr(coordinator, "_MODULE", "operations.transactional_comprehensive_discovery_lane")

    dag_runtime.install_and_verify_dag_native_runtime()

    assert coordinator._MODULE == dag_runtime._CACHED_TRANSACTION_MODULE
    assert canonical_lane._TRANSACTION_SCHEMA
