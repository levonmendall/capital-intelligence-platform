from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FREE_PILOT = ROOT / "operations/free_paper_pilot.py"
EVIDENCE = ROOT / "production_paper_evidence.py"
PUBLICATION = ROOT / "production_context_publication_governed.py"
WEEKEND_TEST = ROOT / "tests/test_weekend_discovery_schedule.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_free_pilot() -> None:
    text = FREE_PILOT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from typing import Any, Mapping, Sequence\n",
        "from typing import Any, Mapping, Sequence\nfrom zoneinfo import ZoneInfo\n",
        label="free-pilot ZoneInfo import",
    )
    text = replace_once(
        text,
        '''DIRECT_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.OPTION,
    }
)
''',
        '''DIRECT_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.OPTION,
    }
)
_MARKET_EVALUATION_TIMEZONE = ZoneInfo("America/New_York")
''',
        label="market evaluation timezone",
    )
    text = replace_once(
        text,
        '''

@dataclass(frozen=True, slots=True)
class FreePaperPilotUniverse:
''',
        '''

def weekday_market_evaluation_scheduled(as_of: datetime) -> bool:
    """Return whether weekday-only market evaluation is scheduled at ``as_of``."""

    if not isinstance(as_of, datetime):
        raise TypeError("as_of must be a datetime")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(_MARKET_EVALUATION_TIMEZONE).weekday() < 5


def instrument_evaluation_scheduled(
    instrument: FreePaperPilotInstrument,
    as_of: datetime,
) -> bool:
    """Return whether fresh evidence is scheduled for one governed instrument."""

    if not isinstance(instrument, FreePaperPilotInstrument):
        raise TypeError("instrument must be a FreePaperPilotInstrument")
    if weekday_market_evaluation_scheduled(as_of):
        return True
    return instrument.trading_session_model is TradingSessionModel.CONTINUOUS_24_7


@dataclass(frozen=True, slots=True)
class FreePaperPilotUniverse:
''',
        label="market evaluation helpers",
    )
    text = replace_once(
        text,
        '''    "free_paper_pilot_universe_payload",
    "load_execution_paper_universe",
''',
        '''    "free_paper_pilot_universe_payload",
    "instrument_evaluation_scheduled",
    "load_execution_paper_universe",
''',
        label="instrument schedule export",
    )
    text = replace_once(
        text,
        '''    "load_free_paper_pilot_universe",
    "validate_pilot_construction",
''',
        '''    "load_free_paper_pilot_universe",
    "validate_pilot_construction",
    "weekday_market_evaluation_scheduled",
''',
        label="weekday schedule export",
    )
    FREE_PILOT.write_text(text, encoding="utf-8")


def patch_evidence() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''from operations.free_paper_pilot import FreePaperPilotInstrument, FreePaperPilotUniverse
''',
        '''from operations.free_paper_pilot import (
    FreePaperPilotInstrument,
    FreePaperPilotUniverse,
    instrument_evaluation_scheduled,
)
''',
        label="evidence schedule import",
    )
    old_probe = '''def _default_probe(
    universe: FreePaperPilotUniverse,
    decision_as_of: datetime,
) -> Mapping[str, object]:
    as_of = _aware(decision_as_of, field_name="decision_as_of")
    listed_instruments = tuple(item for item in universe.instruments if item.execution_asset_class not in DIRECT_EXECUTION_CLASSES)
    direct_instruments = tuple(item for item in universe.instruments if item.execution_asset_class in DIRECT_EXECUTION_CLASSES)
    bars: dict[str, object] = {}
    quotes: dict[str, object] = {}
    client = create_alpaca_paper_client()
    if listed_instruments:
        listed_symbols = tuple(item.symbol for item in listed_instruments)
        bars.update(client.historical_bars(listed_symbols, start=as_of - timedelta(days=_HISTORY_DAYS), end=as_of, timeframe="1Day"))
        quotes.update(client.latest_quotes(listed_symbols))
    direct_market_errors: dict[str, str] = {}
    if direct_instruments:
        direct_client = DirectGlobalMarketClient(
            DirectGlobalMarketUniverse(
                identifier=f"dynamic-direct-evidence:{universe.identifier}",
                provider_identifier="comprehensive-direct-market-evidence.v1",
                instruments=direct_instruments,
                limitations=universe.limitations,
            )
        )
        for instrument in direct_instruments:
            symbol = instrument.symbol
            try:
                symbol_bars = direct_client.historical_bars(
                    (symbol,),
                    start=as_of - timedelta(days=_HISTORY_DAYS),
                    end=as_of,
                    timeframe="1Day",
                )
                symbol_quotes = direct_client.latest_quotes((symbol,))
            except (OSError, TypeError, ValueError, RuntimeError) as error:
                direct_market_errors[symbol] = (
                    f"{type(error).__name__}: {str(error)[:300]}"
                )
                continue
            bars.update(symbol_bars)
            quotes.update(symbol_quotes)
    fred = FREDProvider()
    macro = {series: fred.get_latest_value(series) for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF")}
    company_facts: dict[str, object] = {}
    stock_instruments = tuple(
        item for item in universe.instruments
        if item.execution_asset_class is CandidateAssetClass.US_EQUITY
        and item.instrument_type == "common_stock"
    )
    if stock_instruments:
        sec = SECEdgarProvider()
        for instrument in stock_instruments:
            if instrument.issuer_cik is None:
                continue
            company_facts[instrument.symbol] = sec.fetch_company_facts(
                FilingQuery(
                    cik=instrument.issuer_cik,
                    as_of=as_of,
                    forms=("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"),
                    limit=10_000,
                )
            )
    provider_clock = client.clock()
    return {
        "bars": bars,
        "quotes": quotes,
        "macro": macro,
        "company_facts": company_facts,
        "provider_clock": provider_clock,
        "_direct_market_errors": direct_market_errors,
    }
'''
    new_probe = '''def _default_probe(
    universe: FreePaperPilotUniverse,
    decision_as_of: datetime,
) -> Mapping[str, object]:
    as_of = _aware(decision_as_of, field_name="decision_as_of")
    scheduled_instruments = tuple(
        item
        for item in universe.instruments
        if instrument_evaluation_scheduled(item, as_of)
    )
    scheduled_closed_symbols = tuple(
        item.symbol
        for item in universe.instruments
        if item not in scheduled_instruments
    )
    listed_instruments = tuple(
        item
        for item in scheduled_instruments
        if item.execution_asset_class not in DIRECT_EXECUTION_CLASSES
    )
    direct_instruments = tuple(
        item
        for item in scheduled_instruments
        if item.execution_asset_class in DIRECT_EXECUTION_CLASSES
    )
    bars: dict[str, object] = {}
    quotes: dict[str, object] = {}
    client = None
    if listed_instruments:
        client = create_alpaca_paper_client()
        listed_symbols = tuple(item.symbol for item in listed_instruments)
        bars.update(
            client.historical_bars(
                listed_symbols,
                start=as_of - timedelta(days=_HISTORY_DAYS),
                end=as_of,
                timeframe="1Day",
            )
        )
        quotes.update(client.latest_quotes(listed_symbols))
    direct_market_errors: dict[str, str] = {}
    if direct_instruments:
        direct_client = DirectGlobalMarketClient(
            DirectGlobalMarketUniverse(
                identifier=f"dynamic-direct-evidence:{universe.identifier}",
                provider_identifier="comprehensive-direct-market-evidence.v1",
                instruments=direct_instruments,
                limitations=universe.limitations,
            )
        )
        for instrument in direct_instruments:
            symbol = instrument.symbol
            try:
                symbol_bars = direct_client.historical_bars(
                    (symbol,),
                    start=as_of - timedelta(days=_HISTORY_DAYS),
                    end=as_of,
                    timeframe="1Day",
                )
                symbol_quotes = direct_client.latest_quotes((symbol,))
            except (OSError, TypeError, ValueError, RuntimeError) as error:
                direct_market_errors[symbol] = (
                    f"{type(error).__name__}: {str(error)[:300]}"
                )
                continue
            bars.update(symbol_bars)
            quotes.update(symbol_quotes)
    fred = FREDProvider()
    macro = {
        series: fred.get_latest_value(series)
        for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF")
    }
    company_facts: dict[str, object] = {}
    stock_instruments = tuple(
        item
        for item in scheduled_instruments
        if item.execution_asset_class is CandidateAssetClass.US_EQUITY
        and item.instrument_type == "common_stock"
    )
    if stock_instruments:
        sec = SECEdgarProvider()
        for instrument in stock_instruments:
            if instrument.issuer_cik is None:
                continue
            company_facts[instrument.symbol] = sec.fetch_company_facts(
                FilingQuery(
                    cik=instrument.issuer_cik,
                    as_of=as_of,
                    forms=("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"),
                    limit=10_000,
                )
            )
    provider_clock = (
        client.clock()
        if client is not None
        else {
            "timestamp": as_of.isoformat(),
            "is_open": False,
            "source": "governed_collection_clock",
        }
    )
    return {
        "bars": bars,
        "quotes": quotes,
        "macro": macro,
        "company_facts": company_facts,
        "provider_clock": provider_clock,
        "_direct_market_errors": direct_market_errors,
        "_scheduled_closed_symbols": scheduled_closed_symbols,
    }
'''
    text = replace_once(
        text,
        old_probe,
        new_probe,
        label="schedule-aware evidence probe",
    )
    text = replace_once(
        text,
        '''    raw_direct_market_errors = payload.get("_direct_market_errors", {})
    if not isinstance(raw_direct_market_errors, Mapping):
        raise ProductionPaperEvidenceError(
            "direct-market error detail must be a mapping"
        )
''',
        '''    raw_direct_market_errors = payload.get("_direct_market_errors", {})
    if not isinstance(raw_direct_market_errors, Mapping):
        raise ProductionPaperEvidenceError(
            "direct-market error detail must be a mapping"
        )
    raw_scheduled_closed_symbols = payload.get("_scheduled_closed_symbols", ())
    if not isinstance(raw_scheduled_closed_symbols, Sequence) or isinstance(
        raw_scheduled_closed_symbols,
        (str, bytes),
    ):
        raise ProductionPaperEvidenceError(
            "scheduled-closed symbol detail must be a sequence"
        )
    scheduled_closed_symbols = frozenset(
        str(symbol).strip().upper()
        for symbol in raw_scheduled_closed_symbols
        if str(symbol).strip()
    )
''',
        label="scheduled-closed payload parsing",
    )
    text = replace_once(
        text,
        '''    instrument_by_symbol = {item.symbol: item for item in universe.instruments}
    unknown_holdings = sorted(
''',
        '''    instrument_by_symbol = {item.symbol: item for item in universe.instruments}
    unknown_scheduled_closed = sorted(
        scheduled_closed_symbols - set(instrument_by_symbol)
    )
    if unknown_scheduled_closed:
        raise ProductionPaperEvidenceError(
            "scheduled-closed symbols are outside the governed paper universe: "
            f"{unknown_scheduled_closed}"
        )
    unknown_holdings = sorted(
''',
        label="scheduled-closed universe validation",
    )
    text = replace_once(
        text,
        '''    exclusions: list[tuple[str, tuple[str, ...]]] = []
    for instrument in universe.instruments:
        try:
''',
        '''    exclusions: list[tuple[str, tuple[str, ...]]] = []
    for instrument in universe.instruments:
        if instrument.symbol in scheduled_closed_symbols:
            if instrument.symbol in current_weights:
                raise ProductionPaperEvidenceError(
                    "mandatory holding evidence is unavailable while the instrument's "
                    f"market is scheduled closed: {instrument.symbol}"
                )
            exclusions.append(
                (
                    instrument.instrument_identifier,
                    (
                        "Fresh evaluation is not scheduled because the instrument's "
                        "market is closed for the weekend.",
                    ),
                )
            )
            continue
        try:
''',
        label="scheduled-closed evidence exclusion",
    )
    text = replace_once(
        text,
        '''    benchmark = features_by_symbol.get("VTI")
    if benchmark is None:
        raise ProductionPaperEvidenceError("VTI benchmark evidence is mandatory")
    for instrument in universe.instruments:
''',
        '''    benchmark = features_by_symbol.get("VTI")
    company_candidates_present = any(
        instrument.symbol in features_by_symbol
        and instrument.execution_asset_class is CandidateAssetClass.US_EQUITY
        and instrument.instrument_type == "common_stock"
        for instrument in universe.instruments
    )
    if company_candidates_present and benchmark is None:
        raise ProductionPaperEvidenceError(
            "VTI benchmark evidence is mandatory for active company-equity candidates"
        )
    for instrument in universe.instruments:
''',
        label="conditional VTI benchmark",
    )
    text = replace_once(
        text,
        '''            if (
                instrument.execution_asset_class is CandidateAssetClass.US_EQUITY
                and instrument.instrument_type == "common_stock"
            ):
                candidate, governed = _company_candidate_and_evidence(
''',
        '''            if (
                instrument.execution_asset_class is CandidateAssetClass.US_EQUITY
                and instrument.instrument_type == "common_stock"
            ):
                if benchmark is None:
                    raise ProductionPaperEvidenceError(
                        "VTI benchmark evidence is mandatory for company-equity evidence"
                    )
                candidate, governed = _company_candidate_and_evidence(
''',
        label="company benchmark guard",
    )
    EVIDENCE.write_text(text, encoding="utf-8")


def patch_publication() -> None:
    text = PUBLICATION.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
    write_active_paper_universe,
)
''',
        '''from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
    weekday_market_evaluation_scheduled,
    write_active_paper_universe,
)
''',
        label="publication schedule import",
    )
    old_readiness = '''    try:
        readiness = (readiness_probe or _default_readiness_probe)(base_universe)
    except Exception as error:
        return _blocked(
            cycle_key=cycle_key,
            scheduled_for=scheduled,
            detail=f"Paper-universe provider certification failed: {type(error).__name__}",
            instrument_count=len(universe.instruments),
        )
    configuration_ready = bool(
        _report_value(readiness, "configuration_ready", False)
    )
'''
    new_readiness = '''    weekday_readiness_required = (
        weekday_market_evaluation_scheduled(scheduled)
        or readiness_probe is not None
    )
    if weekday_readiness_required:
        try:
            readiness = (readiness_probe or _default_readiness_probe)(base_universe)
        except Exception as error:
            return _blocked(
                cycle_key=cycle_key,
                scheduled_for=scheduled,
                detail=(
                    "Paper-universe provider certification failed: "
                    f"{type(error).__name__}"
                ),
                instrument_count=len(universe.instruments),
            )
    else:
        readiness = {
            "configuration_ready": True,
            "execution_ready_now": False,
            "market_open": False,
            "account_status": "SCHEDULED_CLOSED",
            "validated_symbols": (),
            "quote_timestamps": (),
            "blockers": (),
            "warnings": (
                "Weekday-only listed-market provider certification was not scheduled.",
            ),
        }
    configuration_ready = bool(
        _report_value(readiness, "configuration_ready", False)
    )
'''
    text = replace_once(
        text,
        old_readiness,
        new_readiness,
        label="weekend readiness short circuit",
    )
    text = replace_once(
        text,
        '''    expected_symbols = tuple(sorted(item.symbol for item in base_universe.instruments))
    quote_symbols = tuple(sorted(str(item[0]).upper() for item in quote_timestamps))
''',
        '''    expected_symbols = (
        tuple(sorted(item.symbol for item in base_universe.instruments))
        if weekday_readiness_required
        else ()
    )
    quote_symbols = tuple(sorted(str(item[0]).upper() for item in quote_timestamps))
''',
        label="scheduled readiness symbols",
    )
    text = replace_once(
        text,
        '''        or quote_symbols != expected_symbols
        or len(quote_timestamps) != len(base_universe.instruments)
''',
        '''        or quote_symbols != expected_symbols
        or len(quote_timestamps) != len(expected_symbols)
''',
        label="scheduled readiness count",
    )
    text = replace_once(
        text,
        '''    latest_quote_date = max(quote_datetimes).date().isoformat()
''',
        '''    latest_quote_date = (
        max(quote_datetimes).date().isoformat()
        if quote_datetimes
        else (
            "scheduled-closed:"
            + decision_as_of.astimezone(
                ZoneInfo(settings.scheduler_timezone)
            ).date().isoformat()
        )
    )
''',
        label="scheduled-closed quote date",
    )
    text = replace_once(
        text,
        '''            lane.asset_class.value: {
                "catalog": lane.catalog_count,
                "deep": lane.deep_analyzed_count,
                "selected": len(lane.selected),
            }
''',
        '''            lane.asset_class.value: {
                "scheduled": lane.scheduled,
                "schedule_reason": lane.schedule_reason,
                "catalog": lane.catalog_count,
                "deep": lane.deep_analyzed_count,
                "selected": len(lane.selected),
            }
''',
        label="lane schedule state persistence",
    )
    text = replace_once(
        text,
        '''        "paper_only": True,
        "real_money_authorized": False,
    }
''',
        '''        "market_evaluation_schedule": (
            "weekday_full"
            if weekday_market_evaluation_scheduled(decision_as_of)
            else "weekend_24_7_only"
        ),
        "paper_only": True,
        "real_money_authorized": False,
    }
''',
        label="market schedule state",
    )
    text = replace_once(
        text,
        '''        detail=(
            "Certified strategic cross-asset wrappers and the daily broad U.S.-company "
            "discovery lane, published complete candidate and exclusion screening, "
            "marked the canonical portfolio, and persisted company-specific evidence."
        ),
''',
        '''        detail=(
            (
                "Certified strategic cross-asset wrappers and the daily broad U.S.-company "
                "discovery lane, published complete candidate and exclusion screening, "
                "marked the canonical portfolio, and persisted company-specific evidence."
            )
            if weekday_market_evaluation_scheduled(decision_as_of)
            else (
                "Published the weekend 24/7 market evaluation; weekday-only instruments "
                "were retained in the governed universe and explicitly excluded as "
                "scheduled closed."
            )
        ),
''',
        label="weekend publication detail",
    )
    PUBLICATION.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = WEEKEND_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''from cio import CandidateAssetClass
''',
        '''from cio import CandidateAssetClass
from governance import TradingSessionModel
''',
        label="test governance import",
    )
    text = replace_once(
        text,
        '''from operations.equity_discovery import (
    discover_us_equities,
    us_equity_discovery_scheduled,
)
''',
        '''from operations.equity_discovery import (
    discover_us_equities,
    us_equity_discovery_scheduled,
)
from operations.free_paper_pilot import (
    FreePaperPilotInstrument,
    FreePaperPilotUniverse,
    instrument_evaluation_scheduled,
    weekday_market_evaluation_scheduled,
)
import production_paper_evidence as paper_evidence
from production_paper_evidence import collect_paper_evidence
''',
        label="test runtime imports",
    )
    addition = '''


def _listed_instrument(
    *,
    symbol: str,
    exposure: str,
    maximum_weight: float,
) -> FreePaperPilotInstrument:
    return FreePaperPilotInstrument(
        symbol=symbol,
        instrument_identifier=f"instrument:us-etf:{symbol.lower()}",
        name=symbol,
        execution_asset_class=CandidateAssetClass.US_ETF,
        economic_exposure=exposure,
        venue="NYSEARCA",
        country_code="US",
        currency="USD",
        instrument_type="fund",
        maximum_weight=maximum_weight,
    )


def _weekend_evidence_universe() -> FreePaperPilotUniverse:
    return FreePaperPilotUniverse(
        identifier="weekend-evidence-test.v1",
        objective="Verify scheduled-closed provider behavior.",
        portfolio_code="COMPOUNDING",
        reporting_currency="USD",
        quote_provider="alpaca-paper-iex",
        execution_mode="internal-simulated-fills-only",
        minimum_cash_weight=0.05,
        maximum_batch_turnover=0.20,
        maximum_single_instrument_weight=0.45,
        maximum_crypto_proxy_weight=0.05,
        maximum_volatility_proxy_weight=0.02,
        maximum_quote_age_minutes=5,
        required_exposure_classes=("us_equity", "volatility"),
        instruments=(
            _listed_instrument(
                symbol="VTI",
                exposure="us_equity",
                maximum_weight=0.45,
            ),
            _listed_instrument(
                symbol="VIXY",
                exposure="volatility",
                maximum_weight=0.02,
            ),
        ),
        limitations=("test-only",),
    )


def test_runtime_schedule_treats_only_24_7_instruments_as_weekend_active():
    listed = _listed_instrument(
        symbol="VTI",
        exposure="us_equity",
        maximum_weight=0.45,
    )
    crypto = FreePaperPilotInstrument(
        symbol="BTCUSD",
        instrument_identifier="instrument:crypto:btcusd",
        name="Bitcoin",
        execution_asset_class=CandidateAssetClass.CRYPTO,
        economic_exposure="crypto",
        venue="CRYPTO",
        country_code="GLOBAL",
        currency="USD",
        settlement_currency="USD",
        instrument_type="token",
        maximum_weight=0.025,
        provider_symbol="BTC-USD",
        provider_kind="yahoo",
        trading_session_model=TradingSessionModel.CONTINUOUS_24_7,
    )

    assert weekday_market_evaluation_scheduled(WEEKEND_AS_OF) is False
    assert instrument_evaluation_scheduled(listed, WEEKEND_AS_OF) is False
    assert instrument_evaluation_scheduled(crypto, WEEKEND_AS_OF) is True
    assert instrument_evaluation_scheduled(listed, WEEKDAY_AS_OF) is True
    assert instrument_evaluation_scheduled(crypto, WEEKDAY_AS_OF) is True


def test_weekend_evidence_collection_skips_listed_provider_calls(monkeypatch):
    class FakeFred:
        @staticmethod
        def get_latest_value(series):
            return {"series": series, "date": "2026-07-31", "value": 4.0}

    def provider_must_not_run():
        raise AssertionError("Alpaca provider was called for scheduled-closed instruments")

    monkeypatch.setattr(
        paper_evidence,
        "create_alpaca_paper_client",
        provider_must_not_run,
    )
    monkeypatch.setattr(paper_evidence, "FREDProvider", FakeFred)

    payload = collect_paper_evidence(
        _weekend_evidence_universe(),
        WEEKEND_AS_OF,
    )

    assert payload["bars"] == {}
    assert payload["quotes"] == {}
    assert set(payload["_scheduled_closed_symbols"]) == {"VTI", "VIXY"}
    assert payload["provider_clock"]["source"] == "governed_collection_clock"
'''
    if addition.strip() in text:
        raise RuntimeError("weekend runtime tests already present")
    WEEKEND_TEST.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def main() -> None:
    patch_free_pilot()
    patch_evidence()
    patch_publication()
    patch_tests()


if __name__ == "__main__":
    main()
