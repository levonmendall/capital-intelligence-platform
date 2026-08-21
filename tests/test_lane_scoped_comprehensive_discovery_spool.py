from pathlib import Path

from cio import CandidateAssetClass
from operations import comprehensive_discovery_input_spool as legacy
from operations import lane_scoped_comprehensive_discovery_spool as spool


def test_lazy_finalizer_catalog_mapping_loads_independent_lane_blobs(tmp_path: Path) -> None:
    equity = legacy._write_pickle_blob(tmp_path, "equity.pkl", ("EQ-A", "EQ-B"))
    crypto = legacy._write_pickle_blob(tmp_path, "crypto.pkl", ("BTCUSD",))
    mapping = spool.LaneScopedCatalogMapping(
        tmp_path,
        {
            CandidateAssetClass.INTERNATIONAL_EQUITY: (
                legacy._descriptor_dict(equity),
                2,
            ),
            CandidateAssetClass.CRYPTO: (
                legacy._descriptor_dict(crypto),
                1,
            ),
        },
    )

    assert len(mapping) == 2
    assert tuple(mapping[CandidateAssetClass.CRYPTO]) == ("BTCUSD",)
    assert tuple(mapping[CandidateAssetClass.INTERNATIONAL_EQUITY]) == (
        "EQ-A",
        "EQ-B",
    )
    assert not isinstance(mapping, dict)


def test_lane_publication_index_requires_matching_lane_for_nonempty_screen(tmp_path: Path) -> None:
    crypto_path = tmp_path / "crypto-publication.json"
    crypto_path.write_text('{"schema_version":"test"}', encoding="utf-8")
    index = spool.LaneScopedPublicationIndex(
        directory=tmp_path,
        catalog_count=7,
        signal_count=3,
        publications=(
            (
                CandidateAssetClass.CRYPTO.value,
                str(crypto_path),
                spool._file_sha256(crypto_path),
            ),
        ),
    )

    assert index.path_for(CandidateAssetClass.CRYPTO, require_lane=True) == crypto_path
    # Empty lanes may borrow a valid publication solely because bounded screening opens
    # the publication before discovering that there are zero records to read.
    assert (
        index.path_for(CandidateAssetClass.FX, require_lane=False)
        == crypto_path
    )
    try:
        index.path_for(CandidateAssetClass.FX, require_lane=True)
    except legacy.ComprehensiveDiscoverySpoolError:
        pass
    else:
        raise AssertionError("nonempty lane accepted another lane's provider publication")


def test_spool_removes_global_catalog_and_publication_reconstruction() -> None:
    source = Path("operations/lane_scoped_comprehensive_discovery_spool.py").read_text(
        encoding="utf-8"
    )

    assert "default_catalog_probe(" not in source
    assert "_merge_certified_catalog(" not in source
    assert "load_asset_reference_component(" in source
    assert "provider-preselection-{index:03d}" in source
    assert '"finalizer_catalog_shards"' in source
    assert '"provider_publications"' in source
    assert '"lane_scoped_memory_builder": True' in source


def test_spawn_safe_finalizer_preserves_canonical_path_with_lazy_lane_inputs() -> None:
    source = Path("operations/spawn_safe_authoritative_acquisition.py").read_text(
        encoding="utf-8"
    )

    assert "LaneScopedCatalogMapping" in source
    assert "LaneScopedPublicationIndex" in source
    assert "core._base._merge_certified_catalog = lane_scoped_merge" in source
    assert "core.build_bounded_terminal_preselection = lane_scoped_terminal" in source
    assert "provider_preselection_path=str(publication_path)" in source
    assert "return current(core, delegate, hydrated, **kwargs)" in source


def test_lane_scoped_spool_does_not_change_investment_authority() -> None:
    source = Path("operations/lane_scoped_comprehensive_discovery_spool.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "authorize_trade",
        "execute_trade",
        "portfolio_construction",
        "real_money_authorized = True",
        "maximum_deep_candidates_per_lane=",
    )
    for token in forbidden:
        assert token not in source
