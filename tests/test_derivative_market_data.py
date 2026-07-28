from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data.derivative_market import (
    DerivativeContractRecord,
    DerivativeContractType,
    DerivativeDataCertificationReport,
    ExerciseStyle,
    MarginRequirementRecord,
    OptionQuoteRecord,
    OptionRight,
    _black_scholes_price,
    build_volatility_surface,
    certify_derivative_data,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)


def _quotes() -> tuple[OptionQuoteRecord, ...]:
    result = []
    spot = 100.0
    for expiration_days in (30, 90):
        expiration = AS_OF + timedelta(days=expiration_days)
        years = expiration_days / 365.25
        for strike in (80.0, 90.0, 100.0, 110.0, 120.0):
            price = _black_scholes_price(
                spot=spot,
                strike=strike,
                time_years=years,
                rate=0.04,
                dividend_yield=0.01,
                volatility=0.24,
                right=OptionRight.CALL,
            )
            result.append(
                OptionQuoteRecord(
                    instrument_id=f"instrument:option:spy:{expiration_days}:{strike:g}:c",
                    underlying_instrument_id="instrument:us-etf:spy",
                    expiration_at=expiration,
                    strike=strike,
                    option_right=OptionRight.CALL,
                    exercise_style=ExerciseStyle.AMERICAN,
                    bid=max(price * 0.995, 0.0001),
                    ask=price * 1.005,
                    underlying_price=spot,
                    risk_free_rate=0.04,
                    dividend_yield=0.01,
                    observed_at=AS_OF - timedelta(minutes=2),
                    available_at=AS_OF - timedelta(minutes=1),
                    source_identifier="databento:opra:test",
                )
            )
    return tuple(result)


def _contract(
    instrument_id: str,
    venue: str,
    contract_type: DerivativeContractType,
    *,
    underlying: str,
) -> DerivativeContractRecord:
    return DerivativeContractRecord(
        instrument_id=instrument_id,
        parent_instrument_id=f"parent:{instrument_id}",
        underlying_instrument_id=underlying,
        venue=venue,
        currency="USD",
        contract_type=contract_type,
        multiplier=100.0 if contract_type is DerivativeContractType.OPTION else 50.0,
        minimum_tick=0.01,
        listing_at=AS_OF - timedelta(days=100),
        expiration_at=AS_OF + timedelta(days=60),
        observed_at=AS_OF - timedelta(minutes=3),
        available_at=AS_OF - timedelta(minutes=2),
        source_identifier="databento:definitions:test",
        strike=100.0 if contract_type is DerivativeContractType.OPTION else None,
        option_right=OptionRight.CALL if contract_type is DerivativeContractType.OPTION else None,
        exercise_style=ExerciseStyle.AMERICAN if contract_type is DerivativeContractType.OPTION else None,
    )


def _margin(instrument_id: str, venue: str, *, effective_at=None) -> MarginRequirementRecord:
    return MarginRequirementRecord(
        instrument_id=instrument_id,
        venue=venue,
        currency="USD",
        initial_margin=12_000.0,
        maintenance_margin=10_000.0,
        effective_at=effective_at or AS_OF - timedelta(hours=2),
        available_at=AS_OF - timedelta(hours=3),
        methodology_identifier=f"{venue.lower()}-margin:test",
        source_identifier=f"{venue.lower()}:margin:test",
    )


def test_volatility_surface_requires_point_in_time_breadth() -> None:
    surface = build_volatility_surface(_quotes(), as_of=AS_OF)

    assert len(surface.points) == 10
    assert {round(item.implied_volatility, 2) for item in surface.points} == {0.24}
    assert surface.method_version == "black-scholes-bisection.v1"
    assert surface.limitations


def test_derivative_contract_margin_and_surface_certification() -> None:
    contracts = (
        _contract(
            "instrument:future:es:test", "CME", DerivativeContractType.FUTURE,
            underlying="instrument:index:spx",
        ),
        _contract(
            "instrument:future:brent:test", "ICE", DerivativeContractType.FUTURE,
            underlying="instrument:commodity:brent",
        ),
        _contract(
            "instrument:option:spy:test", "OCC", DerivativeContractType.OPTION,
            underlying="instrument:us-etf:spy",
        ),
    )
    margins = tuple(_margin(item.instrument_id, item.venue) for item in contracts)
    report = certify_derivative_data(
        contracts=contracts,
        margins=margins,
        surfaces=(build_volatility_surface(_quotes(), as_of=AS_OF),),
        evaluated_at=AS_OF,
    )

    assert report.certified is True
    assert report.covered_venues == ("CME", "ICE", "OCC")
    assert DerivativeDataCertificationReport.from_dict(report.to_dict()) == report


def test_future_effective_margin_does_not_certify_current_trading() -> None:
    contract = _contract(
        "instrument:future:es:test", "CME", DerivativeContractType.FUTURE,
        underlying="instrument:index:spx",
    )
    report = certify_derivative_data(
        contracts=(contract,),
        margins=(
            _margin(
                contract.instrument_id,
                contract.venue,
                effective_at=AS_OF + timedelta(hours=1),
            ),
        ),
        surfaces=(),
        evaluated_at=AS_OF,
        required_venues=("CME",),
    )

    assert report.certified is False
    assert any("not yet effective" in item for item in report.blockers)
