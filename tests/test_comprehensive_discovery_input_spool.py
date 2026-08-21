from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from operations import bounded_comprehensive_discovery_spool as bounded_spool
from operations import comprehensive_discovery_input_spool as spool


def _manifest(tmp_path: Path) -> Path:
    policy = spool._write_pickle_blob(tmp_path, "policy.pkl", {"version": "policy-v1"})
    lane_a = spool._write_pickle_blob(tmp_path, "lane-a.pkl", ("A", "B"))
    lane_b = spool._write_pickle_blob(tmp_path, "lane-b.pkl", ("C",))
    catalogs = spool._write_pickle_blob(tmp_path, "catalogs.pkl", {"equity": ("A", "B")})
    publication = spool._write_pickle_blob(tmp_path, "publication.pkl", {"catalog_count": 2})
    epoch = datetime(2026, 8, 20, 23, 19, tzinfo=timezone.utc)
    material = {
        "schema_version": spool._SCHEMA,
        "request_id": "request-test",
        "release": "release-test",
        "decision_epoch": epoch.isoformat(),
        "policy_version": "policy-v1",
        "policy_blob": spool._descriptor_dict(policy),
        "raw_catalogs_blob": spool._descriptor_dict(catalogs),
        "publication_blob": spool._descriptor_dict(publication),
        "compatibility_rebound_count": 0,
        "nodes": [
            {
                "node_id": "deep-market-evidence:equity",
                "asset_class": "equity",
                "provider_groups": ["alpaca"],
                "input_fingerprint": "fingerprint-a",
                "deadline": epoch.isoformat(),
                "decision_eligible_count": 2,
                "priority": 3,
                "dependencies": [],
                "lane_blob": spool._descriptor_dict(lane_a),
            },
            {
                "node_id": "deep-market-evidence:crypto",
                "asset_class": "crypto",
                "provider_groups": ["coinbase"],
                "input_fingerprint": "fingerprint-b",
                "deadline": epoch.isoformat(),
                "decision_eligible_count": 1,
                "priority": 2,
                "dependencies": ["deep-market-evidence:equity"],
                "lane_blob": spool._descriptor_dict(lane_b),
            },
        ],
        **spool._authority_fields(),
    }
    body = dict(material)
    body["manifest_id"] = spool._digest(material)
    path = tmp_path / "manifest.json"
    spool._atomic_json(path, body)
    return path


def _bounded_manifest(tmp_path: Path) -> Path:
    policy = spool._write_pickle_blob(tmp_path, "bounded-policy.pkl", {"version": "policy-v1"})
    equity = spool._write_pickle_blob(tmp_path, "raw-equity.pkl", ("A", "B"))
    crypto = spool._write_pickle_blob(tmp_path, "raw-crypto.pkl", ("BTC",))
    lane = spool._write_pickle_blob(tmp_path, "lane-equity.pkl", ("A",))
    publication = spool._write_pickle_blob(
        tmp_path,
        "bounded-publication.pkl",
        {"catalog_count": 3},
    )
    epoch = datetime(2026, 8, 20, 23, 20, tzinfo=timezone.utc)
    material = {
        "schema_version": spool._SCHEMA,
        "request_id": "bounded-request-test",
        "release": "release-test",
        "decision_epoch": epoch.isoformat(),
        "policy_version": "policy-v1",
        "policy_blob": spool._descriptor_dict(policy),
        "raw_catalog_shards": [
            {
                "asset_class": CandidateAssetClass.US_EQUITY.value,
                "blob": spool._descriptor_dict(equity),
                "record_count": 2,
            },
            {
                "asset_class": CandidateAssetClass.CRYPTO.value,
                "blob": spool._descriptor_dict(crypto),
                "record_count": 1,
            },
        ],
        "publication_blob": spool._descriptor_dict(publication),
        "compatibility_rebound_count": 0,
        "bounded_memory_builder": True,
        "builder_peak_rss_bytes": {
            "catalog": 100,
            "publication": 200,
            "lanes": {CandidateAssetClass.US_EQUITY.value: 50},
        },
        "nodes": [
            {
                "node_id": f"deep-market-evidence:{CandidateAssetClass.US_EQUITY.value}",
                "asset_class": CandidateAssetClass.US_EQUITY.value,
                "provider_groups": ["eodhd"],
                "input_fingerprint": "fingerprint-equity",
                "deadline": epoch.isoformat(),
                "decision_eligible_count": 1,
                "priority": 0,
                "dependencies": [],
                "lane_blob": spool._descriptor_dict(lane),
            }
        ],
        **spool._authority_fields(),
    }
    body = dict(material)
    body["manifest_id"] = spool._digest(material)
    path = tmp_path / "bounded-manifest.json"
    spool._atomic_json(path, body)
    return path


def test_blob_integrity_is_verified_before_deserialization(tmp_path, monkeypatch) -> None:
    descriptor = spool._write_pickle_blob(tmp_path, "lane.pkl", {"large": list(range(50))})
    path = tmp_path / descriptor.relative_path
    payload = bytearray(path.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    path.write_bytes(payload)

    called = False

    def forbidden_load(_handle):
        nonlocal called
        called = True
        raise AssertionError("pickle.load must not run before checksum verification")

    monkeypatch.setattr(spool.pickle, "load", forbidden_load)
    with pytest.raises(spool.ComprehensiveDiscoverySpoolError, match="integrity mismatch"):
        spool._load_pickle_blob(tmp_path, descriptor)
    assert called is False


def test_lane_loader_materializes_only_selected_lane_and_small_policy(tmp_path, monkeypatch) -> None:
    manifest = _manifest(tmp_path)
    original = spool._load_pickle_blob
    loaded: list[str] = []

    def tracking_load(directory, descriptor):
        loaded.append(descriptor.relative_path)
        return original(directory, descriptor)

    monkeypatch.setattr(spool, "_load_pickle_blob", tracking_load)
    records, policy, descriptor = spool.load_lane_inputs(
        manifest,
        node_id="deep-market-evidence:crypto",
    )

    assert tuple(records) == ("C",)
    assert policy == {"version": "policy-v1"}
    assert descriptor["asset_class"] == "crypto"
    assert loaded == ["policy.pkl", "lane-b.pkl"]
    assert "lane-a.pkl" not in loaded
    assert "catalogs.pkl" not in loaded
    assert "publication.pkl" not in loaded


def test_compact_manifest_reconstructs_every_governed_node_exactly(tmp_path) -> None:
    body = spool.load_manifest(_manifest(tmp_path))
    nodes = spool.nodes_from_manifest(body)

    assert [node.node_id for node in nodes] == [
        "deep-market-evidence:equity",
        "deep-market-evidence:crypto",
    ]
    assert nodes[0].provider_groups == ("alpaca",)
    assert nodes[0].decision_eligible_count == 2
    assert nodes[0].priority == 3
    assert nodes[1].provider_groups == ("coinbase",)
    assert nodes[1].dependencies == ("deep-market-evidence:equity",)
    assert nodes[1].input_fingerprint == "fingerprint-b"


def test_finalizer_payloads_are_separate_from_lane_payloads(tmp_path, monkeypatch) -> None:
    manifest = _manifest(tmp_path)
    original = spool._load_pickle_blob
    loaded: list[str] = []

    def tracking_load(directory, descriptor):
        loaded.append(descriptor.relative_path)
        return original(directory, descriptor)

    monkeypatch.setattr(spool, "_load_pickle_blob", tracking_load)
    catalogs, publication = spool.load_finalizer_inputs(manifest)

    assert catalogs == {"equity": ("A", "B")}
    assert publication == {"catalog_count": 2}
    assert loaded == ["catalogs.pkl", "publication.pkl"]
    assert "lane-a.pkl" not in loaded
    assert "lane-b.pkl" not in loaded
    assert "policy.pkl" not in loaded


def test_bounded_finalizer_rehydrates_shards_only_after_lane_work(tmp_path, monkeypatch) -> None:
    manifest = _bounded_manifest(tmp_path)
    original = spool._load_pickle_blob
    loaded: list[str] = []

    def tracking_load(directory, descriptor):
        loaded.append(descriptor.relative_path)
        return original(directory, descriptor)

    monkeypatch.setattr(spool, "_load_pickle_blob", tracking_load)
    catalogs, publication = bounded_spool.load_finalizer_inputs(manifest)

    assert catalogs == {
        CandidateAssetClass.US_EQUITY: ("A", "B"),
        CandidateAssetClass.CRYPTO: ("BTC",),
    }
    assert publication == {"catalog_count": 3}
    assert loaded == [
        "raw-equity.pkl",
        "raw-crypto.pkl",
        "bounded-publication.pkl",
    ]
    assert "lane-equity.pkl" not in loaded
    assert "bounded-policy.pkl" not in loaded


def test_bounded_builder_never_constructs_global_deep_record_map() -> None:
    source = Path("operations/bounded_comprehensive_discovery_spool.py").read_text(
        encoding="utf-8"
    )

    assert "deep_records_by_node" not in source
    assert "scheduler._build_lane_nodes(" not in source
    assert "_run_stage(\"catalog\"" in source
    assert "_run_stage(\"publication\"" in source
    assert "_run_stage(\n                \"lane\"" in source
    assert "builder_peak_rss_bytes" in source


def test_parent_runner_uses_bounded_builder_and_no_global_deep_records() -> None:
    source = Path("operations/spawn_safe_authoritative_acquisition.py").read_text(
        encoding="utf-8"
    )

    assert "deep_records: Mapping" not in source
    assert "raw_catalogs = core._base.default_catalog_probe" not in source
    assert "_merge_certified_catalog(raw_catalogs" not in source
    assert "operations.bounded_comprehensive_discovery_spool" in source
    assert "subprocess.Popen" in source
    assert "SpoolReference" in source
    assert "load_finalizer_inputs" in source


def test_manifest_authority_is_operational_only(tmp_path) -> None:
    body = spool.load_manifest(_manifest(tmp_path))

    assert body["decision_authority"] is False
    assert body["candidate_authority"] is False
    assert body["sizing_authority"] is False
    assert body["construction_authority"] is False
    assert body["execution_authority"] is False
    assert body["paper_only"] is True
    assert body["real_money_authorized"] is False


def test_bounded_manifest_authority_is_operational_only(tmp_path) -> None:
    body = spool.load_manifest(_bounded_manifest(tmp_path))

    assert body["bounded_memory_builder"] is True
    assert body["decision_authority"] is False
    assert body["candidate_authority"] is False
    assert body["sizing_authority"] is False
    assert body["construction_authority"] is False
    assert body["execution_authority"] is False
    assert body["paper_only"] is True
    assert body["real_money_authorized"] is False
