"""Production-aligned redundant market-evidence probe for comprehensive discovery.

The legacy probe remains the first pass so already-certified provider-native behavior is
preserved. Missing market evidence is then recovered only from independently sourced,
exact-instrument candidates that satisfy the same history contract.  Provider failover
never changes ranking, liquidity thresholds, CIO authority, construction, or execution.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import pstdev
from typing import Any, Mapping, Sequence

import requests

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery_legacy as _legacy
from providers.crypto_venue_history import CoinbaseHistoryProvider, KrakenHistoryProvider
from providers.databento_futures_history import DatabentoFuturesHistoryProvider
from providers.massive_multi_asset import MassiveMultiAssetProvider
from providers.redundancy_audit import (
    ProviderCapabilityKey,
    begin_redundancy_cycle,
    current_redundancy_ledger,
)
from providers.redundant_market_history import (
    MarketHistoryCandidate,
    RedundantMarketHistoryError,
    RedundantMarketHistoryRouter,
)
from providers.tradier_market_data import TradierMarketDataError, TradierMarketDataProvider
from providers.twelve_data_history import TwelveDataHistoryProvider


_DEFAULT_CRYPTO_BINDINGS = Path("config/crypto_venue_bindings.all_markets.json")


def _identity(record: _legacy.DiscoveryCatalogRecord) -> str:
    return (
        str(record.instrument_identifier).strip()
        if record.instrument_identifier
        else f"{record.asset_class.value}:{record.symbol}"
    )


def _massive_future_symbol(symbol: str) -> str:
    normalized = "".join(str(symbol).strip().upper().split())
    # Massive futures examples use the conventional one-digit year suffix (ESU6),
    # while configured discovery roots may use two digits (ESU26).
    if len(normalized) >= 4 and normalized[-2:].isdigit():
        return normalized[:-2] + normalized[-1]
    return normalized


def _crypto_binding(record: _legacy.DiscoveryCatalogRecord) -> Mapping[str, str] | None:
    path = Path(
        os.getenv("CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS", str(_DEFAULT_CRYPTO_BINDINGS))
    ).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = payload.get("bindings") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        return None
    identity = _identity(record).lower()
    compact_symbol = "".join(ch for ch in record.symbol.lower() if ch.isalnum())
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        instrument_id = str(item.get("instrument_id") or "").strip().lower()
        coinbase = str(item.get("coinbase_product_id") or "").strip().upper()
        if instrument_id == identity:
            return {str(k): str(v) for k, v in item.items()}
        if compact_symbol and compact_symbol in instrument_id.replace(":", ""):
            return {str(k): str(v) for k, v in item.items()}
        if coinbase and coinbase.replace("-", "").lower() == compact_symbol:
            return {str(k): str(v) for k, v in item.items()}
    return None


def _feature_from_rows(
    record: _legacy.DiscoveryCatalogRecord,
    rows: Sequence[Mapping[str, object]],
    evidence_identifiers: Sequence[str],
) -> _legacy.DiscoveryMarketFeatures:
    closes = [float(item["c"]) for item in rows]
    volumes = [float(item.get("v", 0.0)) for item in rows]
    daily = [
        closes[index] / closes[index - 1] - 1.0
        for index in range(1, len(closes))
        if closes[index - 1] > 0.0
    ]
    volatility = pstdev(daily[-252:]) * math.sqrt(252.0) if len(daily) > 1 else 0.0
    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1.0)
    window = range(max(0, len(closes) - 20), len(closes))
    adv = sum(closes[index] * volumes[index] for index in window) / min(20, len(closes))
    observed = rows[-1]["t"]
    if not isinstance(observed, datetime):
        raise ValueError("redundant market history is missing a timestamp")
    material = [
        {"t": item["t"].isoformat(), "c": item["c"], "v": item.get("v", 0.0)}
        for item in rows
    ]
    return _legacy.DiscoveryMarketFeatures(
        price=closes[-1],
        observed_at=observed,
        one_month_return=_legacy._period_return(closes, 21),
        three_month_return=_legacy._period_return(closes, 63),
        six_month_return=_legacy._period_return(closes, 126),
        twelve_month_return=_legacy._period_return(closes, 252),
        annualized_volatility=volatility,
        maximum_drawdown=drawdown,
        average_daily_dollar_volume=max(0.0, adv),
        history_bars=len(rows),
        evidence_identifiers=tuple(
            dict.fromkeys(
                (
                    record.source_identifier,
                    *evidence_identifiers,
                    f"redundant-discovery-bars:{record.symbol}:{_legacy._hash(material)}",
                )
            )
        ),
    )


def _alpaca_loader(record, *, as_of, history_days):
    client = _legacy.create_alpaca_paper_client()
    result = client.historical_bars(
        (record.provider_symbol,),
        start=as_of - timedelta(days=history_days),
        end=as_of,
        timeframe="1Day",
    )
    return tuple(result.get(record.provider_symbol, ()))


def _candidate_set(
    record: _legacy.DiscoveryCatalogRecord,
    *,
    as_of: datetime,
    policy: _legacy.ComprehensiveMarketDiscoveryPolicy,
    http_get,
    eodhd_provider,
    tradier: TradierMarketDataProvider,
    massive: MassiveMultiAssetProvider,
    twelve: TwelveDataHistoryProvider,
    coinbase: CoinbaseHistoryProvider,
    kraken: KrakenHistoryProvider,
    databento_futures: DatabentoFuturesHistoryProvider,
) -> tuple[MarketHistoryCandidate, ...]:
    identity = _identity(record)
    history_days = policy.history_days
    candidates: list[MarketHistoryCandidate] = []

    def add(provider, capability, dataset, symbol, loader, *, configured=True, authenticated=False, fixed_income=False, exact=True):
        candidates.append(
            MarketHistoryCandidate(
                provider=provider,
                capability=capability,
                dataset=dataset,
                provider_symbol=symbol,
                instrument_identity=identity,
                loader=loader,
                configured=configured,
                authenticated=authenticated,
                certified_for_evidence_role=True,
                fixed_income=fixed_income,
                exact_security_identity=exact,
            )
        )

    if record.asset_class in {CandidateAssetClass.US_EQUITY, CandidateAssetClass.US_ETF}:
        add("alpaca", "us_equity_history", "IEX", record.provider_symbol, lambda: _alpaca_loader(record, as_of=as_of, history_days=history_days))
        add("tradier", "us_equity_history", "markets/history", record.symbol, lambda: tradier.daily_history(record.symbol, as_of=as_of, history_days=history_days), configured=tradier.configured, authenticated=False)
        add("massive", "us_equity_history", "stocks-aggs", record.symbol, lambda: massive.daily_history("stock", record.symbol, as_of=as_of, history_days=history_days), configured=massive.configured, authenticated=False)
        add("twelve_data", "us_equity_history", "time_series", record.symbol, lambda: twelve.daily_history((record.symbol,), as_of=as_of, history_days=history_days)[1], configured=twelve.configured, authenticated=False)
        add("yahoo", "us_equity_history", "chart", record.provider_symbol, lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get), authenticated=True)
    elif record.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        add("eodhd", "international_equity_history", "eodhd-history", record.provider_symbol, lambda: _legacy._eodhd_rows(record, as_of=as_of, history_days=history_days, provider=eodhd_provider), configured=eodhd_provider.configured, authenticated=False)
        add("twelve_data", "international_equity_history", "time_series", record.provider_symbol, lambda: twelve.daily_history((record.provider_symbol, record.symbol), as_of=as_of, history_days=history_days)[1], configured=twelve.configured, authenticated=False)
        add("yahoo", "international_equity_history", "chart", record.provider_symbol, lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get), authenticated=True)
    elif record.asset_class is CandidateAssetClass.FX:
        add("twelve_data", "fx_history", "time_series", record.provider_symbol, lambda: twelve.daily_history((record.provider_symbol, record.symbol), as_of=as_of, history_days=history_days)[1], configured=twelve.configured, authenticated=False)
        add("massive", "fx_history", "forex-aggs", record.symbol, lambda: massive.daily_history("fx", record.symbol, as_of=as_of, history_days=history_days), configured=massive.configured, authenticated=False)
        add("eodhd", "fx_history", "eodhd-history", record.provider_symbol, lambda: _legacy._eodhd_rows(record, as_of=as_of, history_days=history_days, provider=eodhd_provider), configured=eodhd_provider.configured, authenticated=False)
        add("yahoo", "fx_history", "chart", record.provider_symbol, lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get), authenticated=True)
    elif record.asset_class is CandidateAssetClass.CRYPTO:
        binding = _crypto_binding(record)
        if binding is not None:
            coinbase_symbol = str(binding.get("coinbase_product_id") or "")
            kraken_symbol = str(binding.get("kraken_symbol") or "")
            if coinbase_symbol:
                add("coinbase", "crypto_history", "exchange-candles", coinbase_symbol, lambda: coinbase.daily_history(coinbase_symbol, as_of=as_of, history_days=history_days), authenticated=True)
            if kraken_symbol:
                add("kraken", "crypto_history", "spot-ohlc", kraken_symbol, lambda: kraken.daily_history(kraken_symbol, as_of=as_of, history_days=history_days), authenticated=True)
        add("massive", "crypto_history", "crypto-aggs", record.symbol, lambda: massive.daily_history("crypto", record.symbol, as_of=as_of, history_days=history_days), configured=massive.configured, authenticated=False)
        add("twelve_data", "crypto_history", "time_series", record.provider_symbol, lambda: twelve.daily_history((record.provider_symbol, record.symbol), as_of=as_of, history_days=history_days)[1], configured=twelve.configured, authenticated=False)
        add("yahoo", "crypto_history", "chart", record.provider_symbol, lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get), authenticated=True)
    elif record.asset_class is CandidateAssetClass.FUTURE:
        exact_symbol = record.symbol
        dataset = record.provider_dataset or "GLBX.MDP3"
        add("databento", "futures_history", dataset, exact_symbol, lambda: databento_futures.daily_history(symbol=exact_symbol, venue=record.venue, currency=record.currency, as_of=as_of, history_days=history_days, dataset=dataset), configured=databento_futures.configured, authenticated=False)
        massive_symbol = _massive_future_symbol(exact_symbol)
        add("massive", "futures_history", "futures-aggs", massive_symbol, lambda: massive.daily_history("future", massive_symbol, as_of=as_of, history_days=history_days), configured=massive.configured, authenticated=False)
        # Yahoo is tertiary only when the configured record itself supplies an exact
        # Yahoo symbol; never manufacture a continuous contract for fallback.
        if record.provider_kind == "yahoo" and "=" not in record.provider_symbol:
            add("yahoo", "futures_history", "chart-exact", record.provider_symbol, lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get), authenticated=True)
    elif record.asset_class is CandidateAssetClass.FIXED_INCOME:
        # No generic provider substitution is permitted. A certified exact-security
        # record may use its own EODHD price history; FINRA/Treasury never enter here.
        exact = bool(record.instrument_identifier)
        if record.provider_kind == "eodhd" and exact:
            add("eodhd", "fixed_income_exact_security_history", "eodhd-history", record.provider_symbol, lambda: _legacy._eodhd_rows(record, as_of=as_of, history_days=history_days, provider=eodhd_provider), configured=eodhd_provider.configured, authenticated=False, fixed_income=True, exact=True)
    return tuple(candidates)


def _corroborate_options(
    records: Sequence[_legacy.DiscoveryCatalogRecord],
    features: Mapping[str, _legacy.DiscoveryMarketFeatures],
    *,
    as_of: datetime,
    tradier: TradierMarketDataProvider,
) -> dict[str, _legacy.DiscoveryMarketFeatures]:
    result = dict(features)
    ledger = current_redundancy_ledger()
    key = ProviderCapabilityKey("tradier", "active_option_chain_corroboration", "options/chains")
    if ledger is not None:
        ledger.declare(key, configured=tradier.configured, authenticated=False, routed=True, certified_for_evidence_role=True)
    grouped: dict[tuple[str, date], list[_legacy.DiscoveryCatalogRecord]] = {}
    for record in records:
        if record.asset_class is not CandidateAssetClass.OPTION or not record.underlying_symbol or record.expiration_at is None:
            continue
        grouped.setdefault((record.underlying_symbol, record.expiration_at.date()), []).append(record)
    for (underlying, expiration), option_records in grouped.items():
        if not tradier.configured:
            break
        if ledger is not None:
            ledger.attempted(key)
        try:
            chain = tradier.active_option_chain(underlying, expiration, as_of=as_of)
        except TradierMarketDataError as error:
            if ledger is not None:
                ledger.failed(key, "provider_evidence_unavailable")
            continue
        by_symbol = {item.option_symbol.replace(" ", ""): item for item in chain}
        used_sources: list[str] = []
        for record in option_records:
            compact = record.provider_symbol.replace(" ", "").replace("O:", "")
            evidence = by_symbol.get(compact)
            if evidence is None:
                continue
            existing = result.get(record.symbol)
            if existing is None:
                continue
            used_sources.append(evidence.source_identifier)
            result[record.symbol] = replace(
                existing,
                evidence_identifiers=tuple(dict.fromkeys((*existing.evidence_identifiers, evidence.source_identifier))),
            )
        if used_sources and ledger is not None:
            ledger.used(key, source_identifiers=tuple(dict.fromkeys(used_sources)), failed_over=False)
    return result



def _mark_existing_result_usage(
    records: Sequence[_legacy.DiscoveryCatalogRecord],
    features: Mapping[str, _legacy.DiscoveryMarketFeatures],
) -> None:
    """Record provider-native first-pass successes in the cycle audit."""

    ledger = current_redundancy_ledger()
    if ledger is None:
        return
    for record in records:
        feature = features.get(record.symbol)
        if feature is None:
            continue
        sources = tuple(feature.evidence_identifiers)
        if record.asset_class is CandidateAssetClass.OPTION:
            providers = tuple(
                provider
                for provider in ("databento", "massive")
                if any(provider in source.lower() for source in sources)
            )
            if not providers and record.provider_kind in {"databento", "massive"}:
                providers = (record.provider_kind,)
            for provider in providers:
                dataset = "OPRA.PILLAR" if provider == "databento" else "OPRA"
                key = ProviderCapabilityKey(provider, "option_evidence", dataset)
                ledger.declare(
                    key,
                    configured=True,
                    authenticated=True,
                    routed=True,
                    certified_for_evidence_role=True,
                )
                ledger.used(
                    key,
                    source_identifiers=tuple(
                        source for source in sources if provider in source.lower()
                    ),
                    failed_over=provider == "massive",
                )
            continue
        provider = record.provider_kind.strip().lower()
        capability = {
            CandidateAssetClass.US_EQUITY: "us_equity_history",
            CandidateAssetClass.US_ETF: "us_equity_history",
            CandidateAssetClass.INTERNATIONAL_EQUITY: "international_equity_history",
            CandidateAssetClass.FX: "fx_history",
            CandidateAssetClass.CRYPTO: "crypto_history",
            CandidateAssetClass.FUTURE: "futures_history",
            CandidateAssetClass.FIXED_INCOME: "fixed_income_exact_security_history",
        }.get(record.asset_class)
        if not provider or capability is None:
            continue
        dataset = record.provider_dataset or {
            "alpaca": "IEX",
            "eodhd": "eodhd-history",
            "yahoo": "chart",
            "databento": "GLBX.MDP3",
            "massive": "market-aggs",
        }.get(provider, "provider-native")
        key = ProviderCapabilityKey(provider, capability, dataset)
        ledger.declare(
            key,
            configured=True,
            authenticated=True,
            routed=True,
            certified_for_evidence_role=True,
        )
        ledger.used(key, source_identifiers=sources, failed_over=False)

def default_redundant_market_probe(
    records: Sequence[_legacy.DiscoveryCatalogRecord],
    as_of: datetime,
    policy: _legacy.ComprehensiveMarketDiscoveryPolicy,
    *,
    http_get=requests.get,
) -> Mapping[str, _legacy.DiscoveryMarketFeatures]:
    timestamp = _legacy._aware(as_of, field_name="as_of")
    if current_redundancy_ledger() is None:
        begin_redundancy_cycle(f"cio-market-evidence:{timestamp.isoformat()}", timestamp)

    # Preserve current provider-native behavior first; redundancy only repairs missing
    # authentic evidence and cannot override a valid canonical first-pass result.
    result = dict(_legacy.default_market_probe(records, timestamp, policy, http_get=http_get))
    _mark_existing_result_usage(records, result)
    missing = tuple(record for record in records if record.symbol not in result and record.asset_class is not CandidateAssetClass.OPTION)
    if missing:
        eodhd = _legacy.build_eodhd_provider()
        tradier = TradierMarketDataProvider()
        massive = MassiveMultiAssetProvider()
        twelve = TwelveDataHistoryProvider()
        coinbase = CoinbaseHistoryProvider()
        kraken = KrakenHistoryProvider()
        databento_futures = DatabentoFuturesHistoryProvider()
        router = RedundantMarketHistoryRouter()
        for record in missing:
            candidates = _candidate_set(
                record,
                as_of=timestamp,
                policy=policy,
                http_get=http_get,
                eodhd_provider=eodhd,
                tradier=tradier,
                massive=massive,
                twelve=twelve,
                coinbase=coinbase,
                kraken=kraken,
                databento_futures=databento_futures,
            )
            if not candidates:
                continue
            try:
                routed = router.fetch(candidates, as_of=timestamp, minimum_rows=policy.minimum_history_bars)
            except RedundantMarketHistoryError:
                continue
            result[record.symbol] = _feature_from_rows(record, routed.rows, routed.evidence_identifiers)

    tradier = TradierMarketDataProvider()
    result = _corroborate_options(records, result, as_of=timestamp, tradier=tradier)
    return result


__all__ = ["default_redundant_market_probe"]
