from __future__ import annotations

from pathlib import Path

import pytest

import compounding_aspiration as aspiration


def test_reference_math_is_five_percent_monthly_compounding() -> None:
    definition = aspiration.build_compounding_aspiration()

    assert aspiration.MONTHLY_STRETCH_RATE == 0.05
    assert aspiration.stretch_value(250_000, 1) == pytest.approx(262_500)
    assert aspiration.stretch_value(250_000, 12) == pytest.approx(250_000 * (1.05**12))
    assert definition.annualized_reference_rate == pytest.approx((1.05**12) - 1.0)


def test_reference_has_no_investment_authority() -> None:
    definition = aspiration.build_compounding_aspiration()

    assert definition.reference_only is True
    assert definition.authoritative is False
    assert definition.affects_qualification is False
    assert definition.affects_ranking is False
    assert definition.affects_sizing is False
    assert definition.affects_construction is False
    assert definition.affects_execution is False
    assert definition.can_force_trade is False
    assert definition.can_override_cash is False
    assert definition.can_relax_risk is False
    assert definition.catch_up_risk_authorized is False


def test_serialized_contract_remains_reference_only() -> None:
    payload = aspiration.build_compounding_aspiration().to_dict()

    assert payload["reference_only"] is True
    assert payload["authoritative"] is False
    assert payload["can_force_trade"] is False
    assert payload["can_override_cash"] is False
    assert payload["can_relax_risk"] is False
    assert payload["catch_up_risk_authorized"] is False


def test_invalid_projection_inputs_fail_closed() -> None:
    with pytest.raises(ValueError):
        aspiration.stretch_multiple(-1)
    with pytest.raises(TypeError):
        aspiration.stretch_multiple(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        aspiration.stretch_value(-1, 1)
    with pytest.raises(TypeError):
        aspiration.stretch_value(True, 1)


def test_portfolio_surface_labels_the_aspiration_as_non_authoritative() -> None:
    source = Path("portfolio_ui_refinement.py").read_text(encoding="utf-8")

    assert "COMPOUNDING ASPIRATION" in source
    assert "REFERENCE ONLY" in source
    assert "does not change qualification hurdles, ranking, sizing, construction, execution" in source
    assert "rather than increasing risk to catch up" in source


def test_authority_modules_do_not_import_the_aspiration() -> None:
    authority_paths = (
        Path("canonical_cio.py"),
        Path("portfolio_construction.py"),
        Path("paper_execution_orchestration.py"),
    )
    existing = [path for path in authority_paths if path.exists()]

    assert existing, "expected at least one canonical authority module to be present"
    for path in existing:
        assert "compounding_aspiration" not in path.read_text(encoding="utf-8"), path
