from __future__ import annotations

from types import SimpleNamespace

from operations import comprehensive_discovery_input_spool as legacy
from operations import lane_local_comprehensive_discovery_spool as spool


def test_build_spool_serializes_slotted_descriptor_in_merged_shard(monkeypatch, tmp_path) -> None:
    lane = next(
        item for item in spool.CandidateAssetClass if item is not spool.CandidateAssetClass.OTHER
    )
    request_path = tmp_path / "request.json"
    manifest_path = tmp_path / "manifest.json"
    descriptor = legacy.BlobDescriptor(
        relative_path="merged-catalog.pkl",
        sha256="a" * 64,
        byte_count=123,
    )
    descriptor_body = legacy._descriptor_dict(descriptor)
    request = {
        "request_id": "descriptor-regression",
        "decision_epoch": "2026-08-31T17:00:00+00:00",
        "policy_blob": legacy._descriptor_dict(
            legacy.BlobDescriptor(
                relative_path="policy.pkl",
                sha256="b" * 64,
                byte_count=1,
            )
        ),
    }

    monkeypatch.setattr(
        spool._bounded,
        "_validate_request",
        lambda path, values: (request, SimpleNamespace(version="test-policy")),
    )
    monkeypatch.setattr(spool._legacy, "manifest_available", lambda path: False)
    monkeypatch.setattr(spool._legacy, "_manifest_path", lambda path: manifest_path)
    monkeypatch.setattr(spool, "_candidate_lanes", lambda: (lane,))
    monkeypatch.setattr(spool, "_run_stage", lambda *args, **kwargs: None)

    def load_stage_state(path, state_name):
        if state_name.startswith("publication-lane-"):
            return {
                "dynamic": True,
                "scheduled": True,
                "blob": descriptor_body,
                "record_count": 1,
                "provider_preselection_path": str(tmp_path / "provider.json"),
                "peak_rss_bytes": 1,
            }
        if state_name.startswith("lane-stage-"):
            return {
                "node": {"node_id": "deep-market-evidence:test"},
                "compatibility_rebound": False,
                "peak_rss_bytes": 1,
            }
        raise AssertionError(f"unexpected stage state: {state_name}")

    monkeypatch.setattr(spool._bounded, "_load_stage_state", load_stage_state)

    built = spool.build_spool(
        request_path,
        values={"CAPITAL_INTELLIGENCE_RELEASE": "descriptor-regression-sha"},
    )

    body = legacy.load_manifest(built)
    assert body["raw_catalog_shards"] == [
        {
            "asset_class": lane.value,
            "blob": descriptor_body,
            "record_count": 1,
        }
    ]
