from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from cio import CandidateAssetClass
from governance.bounded_pilot_scope import BoundedPilotCapabilityAuthority
from governance.market_participation import CanonicalMarketParticipationAuthority
from operations.free_paper_pilot import load_free_paper_pilot_universe


def test_registry_separates_observed_from_allocatable_markets() -> None:
    authority = CanonicalMarketParticipationAuthority.load()
    vti = authority.assess(
        instrument_identifier="instrument:us-etf:vti",
        asset_class=CandidateAssetClass.US_ETF,
    )
    stock = authority.assess(
        instrument_identifier="instrument:us-equity:aapl",
        asset_class=CandidateAssetClass.US_EQUITY,
    )
    crypto = authority.assess(
        instrument_identifier="instrument:crypto:btc-usd",
        asset_class=CandidateAssetClass.CRYPTO,
    )
    assert vti.decision_certified and vti.paper_allocatable
    assert stock.monitored and not stock.decision_certified
    assert crypto.monitored and not crypto.paper_allocatable


def test_registry_allocatable_set_matches_fixed_pilot() -> None:
    authority = CanonicalMarketParticipationAuthority.load()
    universe = authority.decision_authority_universe(
        load_free_paper_pilot_universe()
    )
    assert len(universe.instruments) == 15
    assert {item.instrument_identifier for item in universe.instruments} == (
        authority.allocatable_instrument_identifiers
    )


def test_capability_build_filters_dynamic_discovery_to_registry() -> None:
    import application.production_context_executor  # installs the production adapter

    universe = load_free_paper_pilot_universe()
    discovered = replace(
        universe.instruments[0],
        symbol="AAPL",
        instrument_identifier="instrument:us-equity:aapl",
        name="Apple Inc.",
        instrument_type="common_stock",
    )
    dynamic = replace(
        universe,
        identifier=f"{universe.identifier}+dynamic-test",
        instruments=(*universe.instruments, discovered),
    )

    authority = BoundedPilotCapabilityAuthority.from_universe(dynamic)
    payload = authority.coverage_payload()

    assert payload["covered_instrument_count"] == 15
    assert "instrument:us-equity:aapl" not in payload["instrument_identifiers"]


def test_runtime_authority_filters_unregistered_candidate(monkeypatch) -> None:
    import application.production_context_executor as executor_module

    candidate = SimpleNamespace(
        instrument=SimpleNamespace(
            instrument_id="instrument:crypto:btc-usd",
            symbol="BTC-USD",
            asset_class=CandidateAssetClass.CRYPTO,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
            venue="CRYPTO",
            country_code="US",
            instrument_type="spot",
        )
    )
    monkeypatch.setattr(
        executor_module, "candidate_from_payload", lambda _payload: candidate
    )
    context = SimpleNamespace(
        screening_cycle_identifier="screening:test",
        eligible_universe_publication_identifier="eligible:test",
    )
    fake = SimpleNamespace(
        screening_store=SimpleNamespace(
            publication=lambda _identifier: SimpleNamespace(
                candidate_payloads=({"candidate": "btc"},)
            )
        )
    )
    authority_universe = executor_module._candidate_authority_universe(
        fake, context=context
    )
    identifiers = {
        item.instrument_identifier for item in authority_universe.instruments
    }
    assert "instrument:crypto:btc-usd" not in identifiers
    assert len(identifiers) == 15
