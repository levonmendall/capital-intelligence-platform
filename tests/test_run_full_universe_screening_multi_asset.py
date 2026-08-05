from __future__ import annotations

from pathlib import Path

import run_full_universe_screening as runtime
from data import MultiAssetUniverseBuilder
from governance.asset_class_scope import AssetClassScopeAuthority


class ParticipationAuthority:
    def assess(self, **_kwargs):
        raise AssertionError("the wiring test must not assess an instrument")


def test_builder_binds_asset_class_and_market_participation_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    participation = ParticipationAuthority()
    monkeypatch.setattr(
        runtime.CanonicalMarketParticipationAuthority,
        "load",
        lambda: participation,
    )

    database = tmp_path / "asset-class-governance.db"
    builder = runtime.build_multi_asset_universe_builder(
        asset_class_governance_database=str(database)
    )

    assert isinstance(builder, MultiAssetUniverseBuilder)
    assert isinstance(builder.policy.asset_class_authority, AssetClassScopeAuthority)
    assert builder.policy.asset_class_authority.store.path == database
    assert builder.policy.market_participation_authority is participation


def test_asset_class_governance_database_defaults_under_data_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))

    assert runtime._asset_class_governance_database(None) == (
        tmp_path / "asset_class_governance.db"
    )
