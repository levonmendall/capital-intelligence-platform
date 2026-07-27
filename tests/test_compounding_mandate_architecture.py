from pathlib import Path

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
