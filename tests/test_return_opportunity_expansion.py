from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from cio.policy_matrix import DecisionPolicyMatrix
from data.filing import CompanyFact
from operations.equity_discovery import EquityDiscoveryPolicy, discover_us_equities
from operations.free_paper_pilot import (
    FreePaperPilotInstrument,
    load_execution_paper_universe,
    load_free_paper_pilot_universe,
    write_active_paper_universe,
)
from production_paper_evidence import (
    _company_candidate_and_evidence,
    _features,
    _macro_context,
)
from providers.alpaca_paper import AlpacaPaperClient, AlpacaPaperSettings


AS_OF = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _DiscoveryClient:
    def assets(self, **_kwargs):
        return (
            {"symbol": "AAA", "name": "Alpha Operating Company", "exchange": "NASDAQ", "status": "active", "tradable": True, "fractionable": True, "class": "us_equity"},
            {"symbol": "BBB", "name": "Beta Industrial Company", "exchange": "NYSE", "status": "active", "tradable": True, "fractionable": True, "class": "us_equity"},
        )

    def snapshots(self, symbols):
        values = {
            "AAA": {"dailyBar": {"c": 110.0, "v": 2_000_000, "t": "2026-07-29T20:00:00Z"}, "prevDailyBar": {"c": 100.0}},
            "BBB": {"dailyBar": {"c": 50.0, "v": 500_000, "t": "2026-07-29T20:00:00Z"}, "prevDailyBar": {"c": 50.0}},
        }
        return {symbol: values[symbol] for symbol in symbols if symbol in values}

    def historical_bars(self, symbols, **_kwargs):
        result = {}
        start = AS_OF - timedelta(days=420)
        for symbol in symbols:
            rows = []
            for index in range(300):
                if symbol == "AAA":
                    price = 50.0 * (1.0017**index)
                elif symbol == "BBB":
                    price = 50.0 * (1.0002**index)
                else:
                    price = 50.0 * (1.0006**index)
                rows.append({"t": (start + timedelta(days=index)).isoformat(), "c": price, "v": 2_000_000})
            result[symbol] = tuple(rows)
        return result


class _SECProvider:
    def fetch_security_master(self):
        instruments = (
            SimpleNamespace(instrument_id="sec:aaa", issuer_id="SEC:CIK:0000000001", name="Alpha Operating Company"),
            SimpleNamespace(instrument_id="sec:bbb", issuer_id="SEC:CIK:0000000002", name="Beta Industrial Company"),
        )
        listings = (
            SimpleNamespace(instrument_id="sec:aaa", symbol="AAA", venue="NASDAQ"),
            SimpleNamespace(instrument_id="sec:bbb", symbol="BBB", venue="NYSE"),
        )
        return SimpleNamespace(instruments=instruments, listings=listings, retrieved_at=AS_OF)


def _bars(symbol: str, *, growth: float = 1.001) -> tuple[dict[str, object], ...]:
    start = AS_OF - timedelta(days=420)
    return tuple(
        {
            "t": (start + timedelta(days=index)).isoformat(),
            "c": 50.0 * (growth**index),
            "v": 2_000_000.0,
        }
        for index in range(300)
    )


def _fact(year: int, tag: str, value: float, *, instant: bool = False, unit: str = "USD") -> CompanyFact:
    accepted = datetime(year + 1, 2, 15, 16, tzinfo=timezone.utc)
    return CompanyFact(
        cik="0000000001",
        taxonomy="us-gaap",
        tag=tag,
        unit=unit,
        value=value,
        period_start=None if instant else date(year, 1, 1),
        period_end=date(year, 12, 31),
        filed_at=accepted.date(),
        accepted_at=accepted,
        retrieved_at=AS_OF,
        accession_number=f"{year}-{tag}",
        form="10-K",
        fiscal_year=year,
        fiscal_period="FY",
    )


def _company_facts() -> tuple[CompanyFact, ...]:
    values = []
    for year, multiplier in ((2024, 1.0), (2025, 1.2)):
        values.extend(
            (
                _fact(year, "RevenueFromContractWithCustomerExcludingAssessedTax", 1_000 * multiplier),
                _fact(year, "OperatingIncomeLoss", 180 * multiplier),
                _fact(year, "NetIncomeLoss", 140 * multiplier),
                _fact(year, "NetCashProvidedByUsedInOperatingActivities", 200 * multiplier),
                _fact(year, "PaymentsToAcquirePropertyPlantAndEquipment", 40 * multiplier),
                _fact(year, "WeightedAverageNumberOfDilutedSharesOutstanding", 100, unit="shares"),
                _fact(year, "Assets", 1_500 * multiplier, instant=True),
                _fact(year, "Liabilities", 500 * multiplier, instant=True),
                _fact(year, "StockholdersEquity", 1_000 * multiplier, instant=True),
                _fact(year, "CashAndCashEquivalentsAtCarryingValue", 250 * multiplier, instant=True),
                _fact(year, "LongTermDebtNoncurrent", 100, instant=True),
                _fact(year, "AssetsCurrent", 600 * multiplier, instant=True),
                _fact(year, "LiabilitiesCurrent", 250 * multiplier, instant=True),
            )
        )
    return tuple(values)


def test_alpaca_client_supports_broad_asset_and_snapshot_reads() -> None:
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        if url.endswith("/v2/assets"):
            return _Response([{"symbol": "AAA", "status": "active"}])
        return _Response({"AAA": {"dailyBar": {"c": 10}}})

    client = AlpacaPaperClient(
        AlpacaPaperSettings(api_key_id="key", secret_key="secret"),
        http_get=http_get,
    )
    assert client.assets()[0]["symbol"] == "AAA"
    assert "AAA" in client.snapshots(("AAA",))
    assert calls[0][1] == {"status": "active", "asset_class": "us_equity"}


def test_broad_discovery_selects_current_winner_and_preserves_held_company() -> None:
    result = discover_us_equities(
        as_of=AS_OF,
        held_symbols=("BBB",),
        client=_DiscoveryClient(),
        sec_provider=_SECProvider(),
        policy=EquityDiscoveryPolicy(
            maximum_snapshot_assets=10,
            snapshot_batch_size=10,
            deep_shortlist_count=2,
            selected_candidate_count=1,
            minimum_history_bars=252,
        ),
    )
    assert {item.symbol for item in result.selected} == {"AAA", "BBB"}
    assert result.selected[0].symbol == "AAA"
    instruments = result.instruments_for_holdings(("BBB",), policy=EquityDiscoveryPolicy(selected_candidate_count=1, deep_shortlist_count=2))
    weights = {item.symbol: item.maximum_weight for item in instruments}
    assert weights["AAA"] == 0.01
    assert weights["BBB"] == 0.05


def test_stale_premarket_quote_does_not_block_strategic_analysis() -> None:
    features = _features(
        "AAA",
        _bars("AAA"),
        {"t": "2026-07-29T20:00:00Z", "bp": 999.0, "ap": 1000.0},
        as_of=AS_OF,
        cash_expected_return=0.04,
        maximum_quote_age_minutes=5,
    )
    assert features.current_price != 999.5
    assert features.latest_observed_at <= AS_OF


def test_company_equity_receives_exploratory_policy_and_company_evidence() -> None:
    macro, values, identifiers = _macro_context(
        {
            "DGS10": {"date": "2026-07-29", "value": 4.2},
            "T10Y2Y": {"date": "2026-07-29", "value": 0.4},
            "VIXCLS": {"date": "2026-07-29", "value": 17.0},
            "DFF": {"date": "2026-07-29", "value": 3.5},
        },
        as_of=AS_OF,
    )
    features = _features(
        "AAA",
        _bars("AAA", growth=1.0015),
        {"t": "2026-07-30T14:59:00Z", "bp": 78.0, "ap": 78.1},
        as_of=AS_OF,
        cash_expected_return=0.04,
        maximum_quote_age_minutes=5,
    )
    benchmark = _features(
        "VTI",
        _bars("VTI", growth=1.0005),
        {"t": "2026-07-30T14:59:00Z", "bp": 58.0, "ap": 58.1},
        as_of=AS_OF,
        cash_expected_return=0.04,
        maximum_quote_age_minutes=5,
    )
    instrument = FreePaperPilotInstrument(
        symbol="AAA",
        instrument_identifier="instrument:us-equity:aaa",
        name="Alpha Operating Company",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        venue="NASDAQ",
        country_code="US",
        currency="USD",
        instrument_type="common_stock",
        maximum_weight=0.01,
        issuer_cik="1",
    )
    candidate, governed = _company_candidate_and_evidence(
        instrument,
        features,
        company_facts=_company_facts(),
        benchmark=benchmark,
        as_of=AS_OF,
        cash_expected_return=0.04,
        macro=macro,
        macro_values=values,
        macro_identifiers=identifiers,
        current_weight=0.0,
    )
    profile = DecisionPolicyMatrix().resolve(candidate)
    assert governed.company is not None
    assert candidate.instrument.replication_method == "direct-common-equity-exploratory"
    assert profile.identifier == "direct-common-equity-exploratory"
    assert profile.maximum_position_weight == 0.01
    assert profile.entry_persistence_cycles == 1


def test_dynamic_execution_universe_is_resolved_by_publication(tmp_path) -> None:
    base = load_free_paper_pilot_universe()
    stock = FreePaperPilotInstrument(
        symbol="AAA",
        instrument_identifier="instrument:us-equity:aaa",
        name="Alpha Operating Company",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        venue="NASDAQ",
        country_code="US",
        currency="USD",
        instrument_type="common_stock",
        maximum_weight=0.01,
        issuer_cik="1",
    )
    dynamic = replace(base, identifier=base.identifier + "+daily", instruments=(*base.instruments, stock))
    active = tmp_path / "active.json"
    write_active_paper_universe(
        dynamic,
        eligible_universe_publication_identifier="eligible:daily",
        destination=active,
    )
    resolved = load_execution_paper_universe(
        {"eligible_universe_publication_identifier": "eligible:daily"},
        active_path=active,
    )
    assert resolved.symbol_map["AAA"].maximum_weight == 0.01


def test_screening_outcome_ledger_classifies_missed_opportunity(tmp_path) -> None:
    from evaluation.opportunity_outcomes import SQLiteOpportunityOutcomeStore
    from opportunity import (
        AlternativeKind,
        AlternativeUse,
        OpportunityEngine,
        OpportunitySetContext,
    )

    macro, values, identifiers = _macro_context(
        {
            "DGS10": {"date": "2026-07-29", "value": 4.2},
            "T10Y2Y": {"date": "2026-07-29", "value": 0.4},
            "VIXCLS": {"date": "2026-07-29", "value": 17.0},
            "DFF": {"date": "2026-07-29", "value": 3.5},
        },
        as_of=AS_OF,
    )
    features = _features(
        "AAA",
        _bars("AAA", growth=1.0003),
        {"t": "2026-07-30T14:59:00Z", "bp": 54.0, "ap": 54.1},
        as_of=AS_OF,
        cash_expected_return=0.04,
        maximum_quote_age_minutes=5,
    )
    benchmark = _features(
        "VTI",
        _bars("VTI", growth=1.0005),
        {"t": "2026-07-30T14:59:00Z", "bp": 58.0, "ap": 58.1},
        as_of=AS_OF,
        cash_expected_return=0.04,
        maximum_quote_age_minutes=5,
    )
    instrument = FreePaperPilotInstrument(
        symbol="AAA",
        instrument_identifier="instrument:us-equity:aaa",
        name="Alpha Operating Company",
        execution_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure="us_equity",
        venue="NASDAQ",
        country_code="US",
        currency="USD",
        instrument_type="common_stock",
        maximum_weight=0.01,
        issuer_cik="1",
    )
    candidate, _governed = _company_candidate_and_evidence(
        instrument,
        features,
        company_facts=_company_facts(),
        benchmark=benchmark,
        as_of=AS_OF,
        cash_expected_return=0.04,
        macro=macro,
        macro_values=values,
        macro_identifiers=identifiers,
        current_weight=0.0,
    )
    # Deliberately force a qualification rejection without altering the evidence snapshot.
    candidate = replace(candidate, liquidity_score=0.20)
    context = OpportunitySetContext(
        identifier="opportunity:test",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=0.95,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )
    queue = OpportunityEngine().build_queue((candidate,), context)
    assert queue.rejected
    store = SQLiteOpportunityOutcomeStore(tmp_path / "outcomes.db")
    store.append_screening_decisions(
        queue=queue,
        candidates=(candidate,),
        cash_annual_return=0.04,
    )
    assert store.unresolved_symbols(as_of=AS_OF + timedelta(days=22)) == ("AAA",)
    assert store.resolve_due(
        observed_at=AS_OF + timedelta(days=22),
        observed_prices={"AAA": (candidate.current_price * 1.10, "price:aaa:later")},
    ) == 1
    summary = store.summary()
    assert summary.missed_opportunities == 1
    assert summary.avoided_losses == 0
    assert store.verify_integrity() is True
