from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from cio import CandidateAssetClass, CandidateInstrument, RecommendationUniversePolicy
from governance.bounded_pilot_scope import BoundedPilotCapabilityAuthority
from operations.free_paper_pilot import load_free_paper_pilot_universe


AS_OF = datetime(2026, 7, 31, 20, 0, tzinfo=timezone.utc)


def _instrument(symbol: str) -> CandidateInstrument:
    universe = load_free_paper_pilot_universe()
    item = universe.symbol_map[symbol]
    exposure = {
        "international_equity": CandidateAssetClass.INTERNATIONAL_EQUITY,
        "government_bonds": CandidateAssetClass.FIXED_INCOME,
        "investment_grade_credit": CandidateAssetClass.FIXED_INCOME,
        "high_yield_credit": CandidateAssetClass.FIXED_INCOME,
        "broad_commodities": CandidateAssetClass.COMMODITY,
        "gold": CandidateAssetClass.COMMODITY,
        "foreign_exchange": CandidateAssetClass.FX,
        "crypto": CandidateAssetClass.CRYPTO,
        "real_estate": CandidateAssetClass.REAL_ESTATE,
        "managed_futures": CandidateAssetClass.ALTERNATIVE,
        "option_strategies": CandidateAssetClass.OPTION,
        "volatility": CandidateAssetClass.VOLATILITY,
        "market_neutral_alternatives": CandidateAssetClass.ALTERNATIVE,
    }.get(item.economic_exposure)
    return CandidateInstrument(
        instrument_id=item.instrument_identifier,
        symbol=item.symbol,
        name=item.name,
        asset_class=item.execution_asset_class,
        venue=item.venue,
        country_code=item.country_code,
        average_daily_dollar_volume=100_000_000.0,
        data_age_hours=1.0,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:pilot",
        security_master_record_identifiers=(item.instrument_identifier,),
        instrument_type=item.instrument_type,
        economic_exposure_class=exposure,
        uses_derivatives=item.economic_exposure
        in {"managed_futures", "option_strategies", "volatility"},
        replication_method="us-listed-economic-exposure-wrapper",
    )


def test_exact_governed_wrapper_is_directly_recommendation_eligible() -> None:
    universe = load_free_paper_pilot_universe()
    authority = BoundedPilotCapabilityAuthority.from_universe(universe)
    policy = RecommendationUniversePolicy(asset_class_authority=authority)

    assessment = policy.evaluate(_instrument("GOVT"), as_of=AS_OF)

    assert assessment.direct_recommendation_allowed
    assert assessment.asset_class_approval_identifier == (
        f"paper-policy:{universe.identifier}:GOVT"
    )
    assert assessment.asset_class_policy_version == authority.policy_version


def test_identity_or_venue_mismatch_fails_closed() -> None:
    universe = load_free_paper_pilot_universe()
    authority = BoundedPilotCapabilityAuthority.from_universe(universe)
    policy = RecommendationUniversePolicy(asset_class_authority=authority)

    assessment = policy.evaluate(
        replace(_instrument("GOVT"), venue="NASDAQ"),
        as_of=AS_OF,
    )

    assert not assessment.direct_recommendation_allowed
    assert any("venue" in reason for reason in assessment.reasons)


def test_research_overlay_is_explicitly_nonexecuting() -> None:
    universe = load_free_paper_pilot_universe()
    authority = BoundedPilotCapabilityAuthority.from_universe(
        universe,
        research_only=True,
    )

    payload = authority.coverage_payload()

    assert payload["research_only"] is True
    assert payload["execution_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert payload["covered_instrument_count"] == len(universe.instruments)
