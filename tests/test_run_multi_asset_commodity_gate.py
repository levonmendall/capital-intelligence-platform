"""Execution CLIs cannot bypass the commodity baseline prerequisite."""

from __future__ import annotations

import json

from cio import CandidateAssetClass
from evaluation.persistence import serialize_construction
from run_multi_asset_paper_execution import main
from tests.test_multi_asset_paper_execution import (
    AS_OF,
    _buy,
    _construction,
    _profile,
)


def test_multi_asset_cli_blocks_before_portfolio_access_without_commodity_report(
    tmp_path,
    capsys,
) -> None:
    profile = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    construction_path = tmp_path / "construction.json"
    construction_path.write_text(
        json.dumps(
            serialize_construction(
                _construction(_buy(profile.symbol)),
                code_version="test",
            )
        ),
        encoding="utf-8",
    )
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            [
                {
                    "symbol": profile.symbol,
                    "instrument_identifier": profile.instrument_identifier,
                    "asset_class": profile.asset_class.value,
                    "venue": profile.venue,
                    "country_code": profile.country_code,
                    "price_currency": profile.price_currency,
                    "settlement_currency": profile.settlement_currency,
                    "approval_identifier": profile.approval_identifier,
                    "approval_state": profile.approval_state.value,
                    "unlevered": profile.unlevered,
                    "spot_only": profile.spot_only,
                    "custody_settlement_identifier": (
                        profile.custody_settlement_identifier
                    ),
                    "execution_model_version": profile.execution_model_version,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = main(
        [
            "--construction",
            str(construction_path),
            "--profiles",
            str(profiles_path),
            "--decision-identifier",
            "decision:test",
            "--session-provider",
            "tests.multi_asset_execution_factories:session_provider",
            "--quote-provider",
            "tests.multi_asset_execution_factories:quote_provider",
            "--as-of",
            AS_OF.isoformat(),
            "--portfolio-database",
            str(tmp_path / "missing-portfolio.db"),
        ]
    )

    assert result == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert "commodity readiness report is required" in payload["error"]
