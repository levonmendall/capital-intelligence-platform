from pathlib import Path

import json

from portfolio_managers.response import MandateID


def test_only_compounding_mandate_is_configured() -> None:
    source = Path("config/mandates.json").read_text(encoding="utf-8").lower()
    assert '"code": "compounding"' in source
    for retired in (
        "capital preservation",
        "income & stability",
        "balanced allocation",
        "growth opportunities",
        "tactical rotation",
        "opportunistic value",
        "global opportunities",
        "innovation & disruption",
    ):
        assert retired not in source


def test_only_compounding_mandate_enum_remains() -> None:
    assert tuple(MandateID) == (MandateID.COMPOUNDING,)


def test_constraint_document_separates_controls_from_objective() -> None:
    text = Path("docs/COMPOUNDING_MANDATE.md").read_text(encoding="utf-8").lower()
    assert "one investment mandate" in text
    assert "operational constraint profiles" in text
    assert "do not change opportunity ranking" in text


def test_compounding_portfolio_starts_with_250000() -> None:
    mandates = json.loads(Path("config/mandates.json").read_text(encoding="utf-8"))
    assert mandates == [
        {
            "code": "COMPOUNDING",
            "name": "Long-Term Compounding",
            "risk": "Operational constraints only",
            "capital": 250000,
        }
    ]


def test_retired_model_portfolios_are_isolated_from_active_config() -> None:
    assert not Path("config/model_portfolios.json").exists()
    assert Path("config/legacy/model_portfolios.json").exists()
