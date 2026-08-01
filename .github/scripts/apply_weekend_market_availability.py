from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPREHENSIVE = ROOT / "operations/comprehensive_market_discovery.py"
EQUITY = ROOT / "operations/equity_discovery.py"
TEST = ROOT / "tests/test_weekend_discovery_schedule.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, *, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return updated


def patch_comprehensive() -> None:
    text = COMPREHENSIVE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from typing import Any, Callable, Mapping, Sequence\n",
        "from typing import Any, Callable, Mapping, Sequence\nfrom zoneinfo import ZoneInfo\n",
        label="ZoneInfo import",
    )
    text = replace_once(
        text,
        'DEFAULT_DISCOVERY_CONFIG_PATH = Path("config/comprehensive_market_discovery.json")\n',
        '''DEFAULT_DISCOVERY_CONFIG_PATH = Path("config/comprehensive_market_discovery.json")

_DISCOVERY_CALENDAR_TIMEZONE = ZoneInfo("America/New_York")
_DISCOVERY_LANES = (
    CandidateAssetClass.INTERNATIONAL_EQUITY,
    CandidateAssetClass.FX,
    CandidateAssetClass.CRYPTO,
    CandidateAssetClass.FUTURE,
    CandidateAssetClass.FIXED_INCOME,
    CandidateAssetClass.OPTION,
)
_WEEKEND_DISCOVERY_LANES = frozenset({CandidateAssetClass.CRYPTO})
''',
        label="discovery schedule constants",
    )
    text = replace_once(
        text,
        '''def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
''',
        '''def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def scheduled_discovery_lanes(as_of: datetime) -> frozenset[CandidateAssetClass]:
    """Return market families scheduled for fresh discovery at ``as_of``.

    Saturday and Sunday discovery is limited to direct crypto, the governed 24/7
    lane. Exchange-local and 24/5 lanes remain fully fail-closed on weekdays and
    are marked scheduled-closed on weekends instead of being treated as provider
    failures.
    """

    timestamp = _aware(as_of, field_name="as_of")
    if timestamp.astimezone(_DISCOVERY_CALENDAR_TIMEZONE).weekday() >= 5:
        return _WEEKEND_DISCOVERY_LANES
    return frozenset(_DISCOVERY_LANES)
''',
        label="scheduled discovery helper",
    )

    text = replace_once(
        text,
        '''class DiscoveryLaneResult:
    asset_class: CandidateAssetClass
    catalog_count: int
    deep_analyzed_count: int
    selected: tuple[DiscoveredMarketInstrument, ...]
    exclusions: tuple[tuple[str, str], ...]
    source_identifiers: tuple[str, ...]
''',
        '''class DiscoveryLaneResult:
    asset_class: CandidateAssetClass
    catalog_count: int
    deep_analyzed_count: int
    selected: tuple[DiscoveredMarketInstrument, ...]
    exclusions: tuple[tuple[str, str], ...]
    source_identifiers: tuple[str, ...]
    scheduled: bool = True
    schedule_reason: str | None = None
''',
        label="lane schedule fields",
    )
    text = replace_once(
        text,
        '''        if any(item.catalog.asset_class is not self.asset_class for item in self.selected):
            raise ValueError("lane contains a mismatched asset class")
''',
        '''        if any(item.catalog.asset_class is not self.asset_class for item in self.selected):
            raise ValueError("lane contains a mismatched asset class")
        if not isinstance(self.scheduled, bool):
            raise TypeError("scheduled must be a bool")
        if self.scheduled and self.schedule_reason is not None:
            raise ValueError("scheduled lanes cannot carry a schedule_reason")
        if not self.scheduled:
            if not isinstance(self.schedule_reason, str) or not self.schedule_reason.strip():
                raise ValueError("scheduled-closed lanes require a schedule_reason")
            if (
                self.catalog_count
                or self.deep_analyzed_count
                or self.selected
                or self.source_identifiers
            ):
                raise ValueError(
                    "scheduled-closed lanes cannot contain evaluated market data"
                )
''',
        label="lane schedule validation",
    )
    text = replace_once(
        text,
        '''                    "asset_class": lane.asset_class.value,
                    "catalog_count": lane.catalog_count,
''',
        '''                    "asset_class": lane.asset_class.value,
                    "scheduled": lane.scheduled,
                    "schedule_reason": lane.schedule_reason,
                    "catalog_count": lane.catalog_count,
''',
        label="lane schedule serialization",
    )

    text = replace_once(
        text,
        '''def _catalog_from_eodhd(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
    provider: EODHDProvider,
    policy: ComprehensiveMarketDiscoveryPolicy,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:
    result: dict[CandidateAssetClass, list[DiscoveryCatalogRecord]] = {
        item: []
        for item in (
            CandidateAssetClass.INTERNATIONAL_EQUITY,
            CandidateAssetClass.FX,
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.FIXED_INCOME,
        )
    }
''',
        '''def _catalog_from_eodhd(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
    provider: EODHDProvider,
    policy: ComprehensiveMarketDiscoveryPolicy,
    requested_asset_classes: frozenset[CandidateAssetClass] | None = None,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:
    directory_lanes = frozenset(
        {
            CandidateAssetClass.INTERNATIONAL_EQUITY,
            CandidateAssetClass.FX,
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.FIXED_INCOME,
        }
    )
    requested = (
        directory_lanes
        if requested_asset_classes is None
        else frozenset(requested_asset_classes) & directory_lanes
    )
    result: dict[CandidateAssetClass, list[DiscoveryCatalogRecord]] = {
        item: [] for item in requested
    }
''',
        label="requested EODHD lanes",
    )
    text = replace_once(
        text,
        '''    suffix_map = config.yahoo_suffix_map
    for exchange in config.eodhd_exchange_codes:
        snapshot = provider.fetch_dataset(
''',
        '''    suffix_map = config.yahoo_suffix_map
    exchange_lanes = {
        "CC": frozenset({CandidateAssetClass.CRYPTO}),
        "FOREX": frozenset({CandidateAssetClass.FX}),
        "BOND": frozenset({CandidateAssetClass.FIXED_INCOME}),
        "GBOND": frozenset({CandidateAssetClass.FIXED_INCOME}),
    }
    for exchange in config.eodhd_exchange_codes:
        possible_lanes = exchange_lanes.get(
            exchange,
            frozenset({CandidateAssetClass.INTERNATIONAL_EQUITY}),
        )
        if not possible_lanes & requested:
            continue
        snapshot = provider.fetch_dataset(
''',
        label="EODHD exchange schedule filter",
    )
    text = replace_once(
        text,
        '''            else:
                continue
            yahoo_suffix = suffix_map.get(exchange, "")
''',
        '''            else:
                continue
            if asset_class not in requested:
                continue
            yahoo_suffix = suffix_map.get(exchange, "")
''',
        label="EODHD asset schedule filter",
    )

    text = regex_once(
        text,
        r'''def default_catalog_probe\(\n.*?\n    return result\n\n\ndef _yahoo_rows''',
        '''def default_catalog_probe(
    as_of: datetime,
    *,
    config: ComprehensiveMarketDiscoveryConfig | None = None,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    eodhd_provider: EODHDProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:
    timestamp = _aware(as_of, field_name="as_of")
    resolved_config = config or load_comprehensive_market_discovery_config()
    resolved_policy = policy or ComprehensiveMarketDiscoveryPolicy()
    active_lanes = scheduled_discovery_lanes(timestamp)
    provider = eodhd_provider or build_eodhd_provider()
    result = {
        key: list(value)
        for key, value in _catalog_from_eodhd(
            as_of=timestamp,
            config=resolved_config,
            provider=provider,
            policy=resolved_policy,
            requested_asset_classes=active_lanes,
        ).items()
    }
    for asset_class in _DISCOVERY_LANES:
        result.setdefault(asset_class, [])
    if CandidateAssetClass.FUTURE in active_lanes:
        result[CandidateAssetClass.FUTURE] = list(
            _futures_catalog(as_of=timestamp, config=resolved_config)
        )
    if CandidateAssetClass.OPTION in active_lanes:
        result[CandidateAssetClass.OPTION] = list(
            _option_catalog(
                as_of=timestamp,
                config=resolved_config,
                policy=resolved_policy,
                databento_options_provider=databento_options_provider,
            )
        )
    return result


def _yahoo_rows''',
        label="default catalog schedule",
    )

    text = replace_once(
        text,
        '''    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    catalogs = (catalog_probe or default_catalog_probe)(timestamp)
''',
        '''    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    scheduled_lanes = scheduled_discovery_lanes(timestamp)
    catalogs = (catalog_probe or default_catalog_probe)(timestamp)
''',
        label="discover active schedule",
    )
    text = replace_once(
        text,
        '''    for asset_class in (
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.OPTION,
    ):
        raw = catalogs.get(asset_class, ())
''',
        '''    for asset_class in _DISCOVERY_LANES:
        if asset_class not in scheduled_lanes:
            schedule_reason = "weekend_market_closed"
            lanes.append(
                DiscoveryLaneResult(
                    asset_class=asset_class,
                    catalog_count=0,
                    deep_analyzed_count=0,
                    selected=(),
                    exclusions=(("__lane__", schedule_reason),),
                    source_identifiers=(),
                    scheduled=False,
                    schedule_reason=schedule_reason,
                )
            )
            manifest_material.append(
                {
                    "asset_class": asset_class.value,
                    "scheduled": False,
                    "schedule_reason": schedule_reason,
                    "catalog": 0,
                    "deep": 0,
                    "selected": [],
                    "sources": [],
                }
            )
            continue
        raw = catalogs.get(asset_class, ())
''',
        label="closed lane short circuit",
    )
    text = replace_once(
        text,
        '''                "asset_class": asset_class.value,
                "catalog": len(records),
''',
        '''                "asset_class": asset_class.value,
                "scheduled": True,
                "schedule_reason": None,
                "catalog": len(records),
''',
        label="active lane manifest",
    )
    text = replace_once(
        text,
        '''    if any(not lane.selected for lane in lanes):
        missing = tuple(lane.asset_class.value for lane in lanes if not lane.selected)
''',
        '''    if any(lane.scheduled and not lane.selected for lane in lanes):
        missing = tuple(
            lane.asset_class.value
            for lane in lanes
            if lane.scheduled and not lane.selected
        )
''',
        label="scheduled lane fail closed",
    )
    text = replace_once(
        text,
        '''    "discover_comprehensive_markets",
    "load_comprehensive_market_discovery_config",
''',
        '''    "discover_comprehensive_markets",
    "load_comprehensive_market_discovery_config",
    "scheduled_discovery_lanes",
''',
        label="scheduled helper export",
    )

    COMPREHENSIVE.write_text(text, encoding="utf-8")


def patch_equity() -> None:
    text = EQUITY.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from typing import Any, Mapping, Sequence\n",
        "from typing import Any, Mapping, Sequence\nfrom zoneinfo import ZoneInfo\n",
        label="equity ZoneInfo import",
    )
    text = replace_once(
        text,
        '''_ALLOWED_EXCHANGES = frozenset({"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA"})
''',
        '''_ALLOWED_EXCHANGES = frozenset({"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA"})
_US_EQUITY_DISCOVERY_TIMEZONE = ZoneInfo("America/New_York")
''',
        label="equity schedule timezone",
    )
    text = replace_once(
        text,
        '''def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
''',
        '''def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def us_equity_discovery_scheduled(as_of: datetime) -> bool:
    """Return whether fresh U.S.-equity discovery is scheduled at ``as_of``."""

    timestamp = _aware(as_of, field_name="as_of")
    return timestamp.astimezone(_US_EQUITY_DISCOVERY_TIMEZONE).weekday() < 5
''',
        label="equity schedule helper",
    )
    text = replace_once(
        text,
        '''    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or EquityDiscoveryPolicy()
    alpaca = client or create_alpaca_paper_client()
''',
        '''    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or EquityDiscoveryPolicy()
    if not us_equity_discovery_scheduled(timestamp):
        local_date = timestamp.astimezone(_US_EQUITY_DISCOVERY_TIMEZONE).date()
        material = {
            "as_of": timestamp.isoformat(),
            "policy": resolved.version,
            "schedule": "weekend_market_closed",
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return EquityDiscoveryResult(
            identifier=(
                f"equity-discovery:{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}:"
                f"{digest[:16]}"
            ),
            as_of=timestamp,
            policy_version=resolved.version,
            screened_asset_count=0,
            snapshot_covered_count=0,
            deep_shortlist_count=0,
            selected=(),
            observed_prices=(),
            exclusions=(("__lane__", "weekend_market_closed"),),
            security_master_snapshot_identifier=(
                f"schedule:us-equity:{local_date.isoformat()}:closed"
            ),
        )
    alpaca = client or create_alpaca_paper_client()
''',
        label="equity weekend short circuit",
    )
    text = replace_once(
        text,
        '''    "EquityDiscoveryResult",
    "discover_us_equities",
''',
        '''    "EquityDiscoveryResult",
    "discover_us_equities",
    "us_equity_discovery_scheduled",
''',
        label="equity helper export",
    )
    EQUITY.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST.write_text(
        '''from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery as comprehensive
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryConfig,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    default_catalog_probe,
    discover_comprehensive_markets,
    scheduled_discovery_lanes,
)
from operations.equity_discovery import (
    discover_us_equities,
    us_equity_discovery_scheduled,
)


WEEKEND_AS_OF = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
WEEKDAY_AS_OF = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def _record(asset_class: CandidateAssetClass, symbol: str) -> DiscoveryCatalogRecord:
    expiration = (
        WEEKEND_AS_OF + timedelta(days=90)
        if asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION}
        else None
    )
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        economic_exposure={
            CandidateAssetClass.INTERNATIONAL_EQUITY: "international_equity",
            CandidateAssetClass.FX: "foreign_exchange",
            CandidateAssetClass.CRYPTO: "crypto",
            CandidateAssetClass.FUTURE: "broad_commodities",
            CandidateAssetClass.FIXED_INCOME: "government_bonds",
            CandidateAssetClass.OPTION: "option_strategies",
        }[asset_class],
        venue="TEST",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type={
            CandidateAssetClass.INTERNATIONAL_EQUITY: "common_stock",
            CandidateAssetClass.FX: "spot",
            CandidateAssetClass.CRYPTO: "token",
            CandidateAssetClass.FUTURE: "future",
            CandidateAssetClass.FIXED_INCOME: "bond",
            CandidateAssetClass.OPTION: "option",
        }[asset_class],
        provider_kind="test",
        source_identifier=f"source:{symbol}",
        expiration_at=expiration,
        underlying_symbol="SPY" if asset_class is CandidateAssetClass.OPTION else None,
        strike=500.0 if asset_class is CandidateAssetClass.OPTION else None,
        option_right="call" if asset_class is CandidateAssetClass.OPTION else None,
        contract_multiplier=100.0 if asset_class is CandidateAssetClass.OPTION else 1.0,
    )


def _all_catalogs(_as_of):
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: [
            _record(CandidateAssetClass.INTERNATIONAL_EQUITY, "EQ")
        ],
        CandidateAssetClass.FX: [_record(CandidateAssetClass.FX, "EURUSD")],
        CandidateAssetClass.CRYPTO: [_record(CandidateAssetClass.CRYPTO, "BTCUSD")],
        CandidateAssetClass.FUTURE: [_record(CandidateAssetClass.FUTURE, "ESZ26")],
        CandidateAssetClass.FIXED_INCOME: [
            _record(CandidateAssetClass.FIXED_INCOME, "UST")
        ],
        CandidateAssetClass.OPTION: [
            _record(CandidateAssetClass.OPTION, "SPYOPTION")
        ],
    }


def test_weekend_schedule_keeps_only_crypto_active():
    assert scheduled_discovery_lanes(WEEKEND_AS_OF) == frozenset(
        {CandidateAssetClass.CRYPTO}
    )
    assert len(scheduled_discovery_lanes(WEEKDAY_AS_OF)) == 6
    assert us_equity_discovery_scheduled(WEEKEND_AS_OF) is False
    assert us_equity_discovery_scheduled(WEEKDAY_AS_OF) is True


def test_weekend_comprehensive_discovery_evaluates_only_crypto():
    evaluated = []

    def market_probe(records, _as_of, _policy):
        evaluated.extend(item.asset_class for item in records)
        return {
            item.symbol: DiscoveryMarketFeatures(
                price=100.0,
                observed_at=WEEKEND_AS_OF,
                one_month_return=0.01,
                three_month_return=0.02,
                six_month_return=0.03,
                twelve_month_return=0.04,
                annualized_volatility=0.20,
                maximum_drawdown=-0.10,
                average_daily_dollar_volume=20_000_000.0,
                history_bars=500,
                evidence_identifiers=(f"evidence:{item.symbol}",),
            )
            for item in records
        }

    result = discover_comprehensive_markets(
        as_of=WEEKEND_AS_OF,
        catalog_probe=_all_catalogs,
        market_probe=market_probe,
    )

    assert len(result.lanes) == 6
    assert evaluated == [CandidateAssetClass.CRYPTO]
    assert {item.catalog.asset_class for item in result.selected} == {
        CandidateAssetClass.CRYPTO
    }
    lane_by_class = {lane.asset_class: lane for lane in result.lanes}
    assert lane_by_class[CandidateAssetClass.CRYPTO].scheduled is True
    for asset_class, lane in lane_by_class.items():
        if asset_class is CandidateAssetClass.CRYPTO:
            continue
        assert lane.scheduled is False
        assert lane.schedule_reason == "weekend_market_closed"
        assert lane.selected == ()


def test_weekend_default_catalog_does_not_call_futures_or_options(monkeypatch):
    crypto = _record(CandidateAssetClass.CRYPTO, "BTCUSD")

    def directory_probe(**kwargs):
        assert kwargs["requested_asset_classes"] == frozenset(
            {CandidateAssetClass.CRYPTO}
        )
        return {CandidateAssetClass.CRYPTO: [crypto]}

    def unavailable_probe(**_kwargs):
        raise AssertionError("weekday-only provider path was called on a weekend")

    monkeypatch.setattr(comprehensive, "_catalog_from_eodhd", directory_probe)
    monkeypatch.setattr(comprehensive, "_futures_catalog", unavailable_probe)
    monkeypatch.setattr(comprehensive, "_option_catalog", unavailable_probe)

    result = default_catalog_probe(
        WEEKEND_AS_OF,
        config=ComprehensiveMarketDiscoveryConfig(
            eodhd_exchange_codes=("CC",),
            futures_roots=(),
            option_underlyings=(),
            yahoo_exchange_suffixes=(),
        ),
        eodhd_provider=object(),
        databento_options_provider=object(),
    )

    assert result[CandidateAssetClass.CRYPTO] == [crypto]
    assert all(
        result[asset_class] == []
        for asset_class in result
        if asset_class is not CandidateAssetClass.CRYPTO
    )


def test_weekend_us_equity_discovery_does_not_call_providers():
    class ProviderMustNotRun:
        def __getattr__(self, name):
            raise AssertionError(f"provider method {name} was called on a weekend")

    result = discover_us_equities(
        as_of=WEEKEND_AS_OF,
        client=ProviderMustNotRun(),
        sec_provider=ProviderMustNotRun(),
    )

    assert result.selected == ()
    assert result.observed_prices == ()
    assert result.exclusions == (("__lane__", "weekend_market_closed"),)
    assert result.security_master_snapshot_identifier.endswith(":closed")
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_comprehensive()
    patch_equity()
    write_tests()


if __name__ == "__main__":
    main()
