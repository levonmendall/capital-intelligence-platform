from __future__ import annotations

import inspect

from cio import CandidateAssetClass
from operations import comprehensive_discovery_runtime_contract as runtime_contract
from operations import lane_local_comprehensive_discovery_coordinator as coordinator
from operations import lane_local_comprehensive_discovery_spool as lane_local


def test_lane_shard_catalogs_retain_only_current_lane(monkeypatch, tmp_path):
    shards = (
        {"asset_class": CandidateAssetClass.CRYPTO.value, "blob": {"id": "crypto"}},
        {"asset_class": CandidateAssetClass.FX.value, "blob": {"id": "fx"}},
    )
    payloads = {"crypto": ("BTC",), "fx": ("EURUSD",)}

    monkeypatch.setattr(lane_local._legacy, "_descriptor", lambda value: value)
    monkeypatch.setattr(
        lane_local._legacy,
        "_load_pickle_blob",
        lambda _directory, descriptor: payloads[descriptor["id"]],
    )
    catalogs = lane_local.LaneShardCatalogs(tmp_path / "manifest.json", shards)

    assert catalogs[CandidateAssetClass.CRYPTO] == ("BTC",)
    assert catalogs._cached_key is CandidateAssetClass.CRYPTO
    assert catalogs[CandidateAssetClass.FX] == ("EURUSD",)
    assert catalogs._cached_key is CandidateAssetClass.FX
    assert catalogs._cached_value == ("EURUSD",)


def test_catalog_stage_reuses_lane_scoped_reference_components():
    source = inspect.getsource(lane_local._catalog_lane_stage)
    assert "supervised._load_asset_component(" in source
    assert "CandidateAssetClass.FUTURE" in source
    assert "default_catalog_probe(" not in source


def test_provider_publication_is_built_per_lane_only():
    source = inspect.getsource(lane_local._publication_lane_stage)
    assert "{asset_class: merged}" in source
    assert "provider_preselection_path=publication_path" in source
    assert "raw_catalogs" not in source


def test_finalizer_uses_lazy_merged_catalogs_and_lane_publications():
    source = inspect.getsource(lane_local._install_lane_local_finalizer)
    assert "isinstance(catalogs, LaneShardCatalogs)" in source
    assert "return catalogs" in source
    assert "lane_paths.get(str(progress_label))" in source
    assert "provider_preselection_path=publication_path" in source


def test_coordinator_keeps_integrity_descriptors_without_dataclass_dict_access():
    source = inspect.getsource(coordinator.build_spool)
    assert "_descriptor_dict" in source
    assert ".__dict__" not in source
    assert "raw_catalogs" not in source


def test_runtime_contract_installs_lane_local_overlay_after_spawn_safe_boundary():
    source = inspect.getsource(runtime_contract.install_comprehensive_discovery_runtime_contract)
    assert source.index("_install_spawn_safe_acquisition()") < source.index(
        "_install_lane_local_spool()"
    )


def test_lane_local_module_has_no_investment_authority():
    source = inspect.getsource(lane_local)
    assert "real_money_authorized\": True" not in source
    assert "decision_authority\": True" not in source
    assert "construction_authority\": True" not in source
    assert "execution_authority\": True" not in source
