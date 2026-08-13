"""Production-aligned redundant market-evidence probe for comprehensive discovery.

The provider-native probe runs first. Only records still missing authentic evidence get a
fallback candidate graph, avoiding an all-universe set of loader closures in memory.
Databento is intentionally absent from the active routing graph.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import pstdev
from typing import Mapping, Sequence

import requests

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery_legacy as _legacy
from providers.alpaca_crypto_history import AlpacaCryptoHistoryError, AlpacaCryptoHistoryProvider
from providers.crypto_venue_history import CoinbaseHistoryProvider, KrakenHistoryProvider
from providers.massive_multi_asset import MassiveMultiAssetProvider
from providers.redundancy_audit import ProviderCapabilityKey, begin_redundancy_cycle, current_redundancy_ledger
from providers.redundant_market_history import MarketHistoryCandidate, RedundantMarketHistoryError, RedundantMarketHistoryRouter
from providers.tradier_market_data import TradierMarketDataError, TradierMarketDataProvider
from providers.twelve_data_history import TwelveDataHistoryProvider

_DEFAULT_CRYPTO_BINDINGS = Path("config/crypto_venue_bindings.all_markets.json")
_ALPACA_CRYPTO_DATASET = "v1beta3/crypto/us/bars"


def _identity(record: _legacy.DiscoveryCatalogRecord) -> str:
    return str(record.instrument_identifier).strip() if record.instrument_identifier else f"{record.asset_class.value}:{record.symbol}"


def _massive_future_symbol(symbol: str) -> str:
    normalized = "".join(str(symbol).strip().upper().split())
    return normalized[:-2] + normalized[-1] if len(normalized) >= 4 and normalized[-2:].isdigit() else normalized


def _catalog_source_code(record: _legacy.DiscoveryCatalogRecord) -> str:
    """Recover the provider-native EODHD code preserved in discovery lineage."""

    source = str(record.source_identifier or "").split("|", 1)[0]
    code = source.rsplit(":", 1)[-1].strip().upper()
    return code or str(record.provider_symbol).strip().upper()


def _eodhd_provider_record(record: _legacy.DiscoveryCatalogRecord) -> _legacy.DiscoveryCatalogRecord:
    """Return the exact EODHD identity even when the catalog carries a Yahoo alias."""

    code = _catalog_source_code(record)
    if record.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        exchange = record.symbol.rsplit("_", 1)[-1] if "_" in record.symbol else record.venue
    elif record.asset_class is CandidateAssetClass.FX:
        exchange = "FOREX"
    elif record.asset_class is CandidateAssetClass.CRYPTO:
        exchange = "CC"
    elif record.asset_class is CandidateAssetClass.FIXED_INCOME:
        current = str(record.provider_symbol).strip().upper()
        exchange = current.rsplit(".", 1)[-1] if "." in current else record.venue
    else:
        return record
    exchange = str(exchange).strip().upper()
    provider_symbol = code if code.endswith(f".{exchange}") else f"{code}.{exchange}"
    return replace(record, provider_symbol=provider_symbol, provider_kind="eodhd")


def _primary_probe_record(record: _legacy.DiscoveryCatalogRecord) -> _legacy.DiscoveryCatalogRecord:
    """Route high-volume lanes to the efficient provider before legacy per-symbol Yahoo."""

    if record.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        return _eodhd_provider_record(record)
    if record.asset_class in {CandidateAssetClass.FX, CandidateAssetClass.CRYPTO}:
        # Twelve Data and batched Alpaca are handled by the redundancy stage. Marking
        # these unbound prevents the legacy probe from issuing one Yahoo request per
        # instrument before those preferred providers get a chance to run.
        return replace(record, provider_kind="unbound")
    return record


def _crypto_binding(record: _legacy.DiscoveryCatalogRecord) -> Mapping[str, str] | None:
    path = Path(os.getenv("CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS", str(_DEFAULT_CRYPTO_BINDINGS))).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = payload.get("bindings") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        return None
    identity = _identity(record).lower()
    compact = "".join(ch for ch in record.symbol.lower() if ch.isalnum())
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        instrument_id = str(item.get("instrument_id") or "").strip().lower()
        coinbase = str(item.get("coinbase_product_id") or "").strip().upper()
        if instrument_id == identity or (compact and compact in instrument_id.replace(":", "")) or (coinbase and coinbase.replace("-", "").lower() == compact):
            return {str(k): str(v) for k, v in item.items()}
    return None


def _alpaca_crypto_symbol(record: _legacy.DiscoveryCatalogRecord, binding: Mapping[str, str] | None) -> str:
    raw = str((binding or {}).get("coinbase_product_id") or record.provider_symbol or record.symbol).strip().upper()
    if "/" in raw:
        return raw
    if "-" in raw:
        left, right = raw.rsplit("-", 1)
        if left and right:
            return f"{left}/{right}"
    return raw


def _feature_from_rows(record, rows, evidence_identifiers):
    closes = [float(item["c"]) for item in rows]
    volumes = [float(item.get("v", 0.0)) for item in rows]
    daily = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0.0]
    volatility = pstdev(daily[-252:]) * math.sqrt(252.0) if len(daily) > 1 else 0.0
    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1.0)
    window = range(max(0, len(closes) - 20), len(closes))
    adv = sum(closes[i] * volumes[i] for i in window) / min(20, len(closes))
    observed = rows[-1]["t"]
    if not isinstance(observed, datetime):
        raise ValueError("redundant market history is missing a timestamp")
    material = [{"t": item["t"].isoformat(), "c": item["c"], "v": item.get("v", 0.0)} for item in rows]
    return _legacy.DiscoveryMarketFeatures(
        price=closes[-1], observed_at=observed,
        one_month_return=_legacy._period_return(closes, 21),
        three_month_return=_legacy._period_return(closes, 63),
        six_month_return=_legacy._period_return(closes, 126),
        twelve_month_return=_legacy._period_return(closes, 252),
        annualized_volatility=volatility, maximum_drawdown=drawdown,
        average_daily_dollar_volume=max(0.0, adv), history_bars=len(rows),
        evidence_identifiers=tuple(dict.fromkeys((record.source_identifier, *evidence_identifiers, f"redundant-discovery-bars:{record.symbol}:{_legacy._hash(material)}"))),
    )


def _alpaca_loader(record, *, as_of, history_days):
    client = _legacy.create_alpaca_paper_client()
    result = client.historical_bars((record.provider_symbol,), start=as_of - timedelta(days=history_days), end=as_of, timeframe="1Day")
    return tuple(result.get(record.provider_symbol, ()))


def _candidate_set(record, *, as_of, policy, http_get, eodhd_provider, tradier, massive, twelve, coinbase, kraken, alpaca_crypto_rows):
    identity = _identity(record)
    history_days = policy.history_days
    candidates: list[MarketHistoryCandidate] = []

    def add(provider, capability, dataset, symbol, loader, *, configured=True, authenticated=False, fixed_income=False, exact=True):
        candidates.append(MarketHistoryCandidate(provider=provider, capability=capability, dataset=dataset, provider_symbol=symbol, instrument_identity=identity, loader=loader, configured=configured, authenticated=authenticated, certified_for_evidence_role=True, fixed_income=fixed_income, exact_security_identity=exact))

    yahoo = lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get)
    eod_record = _eodhd_provider_record(record)
    eod = lambda: _legacy._eodhd_rows(eod_record, as_of=as_of, history_days=history_days, provider=eodhd_provider)

    if record.asset_class in {CandidateAssetClass.US_EQUITY, CandidateAssetClass.US_ETF}:
        add("alpaca", "us_equity_history", "IEX", record.provider_symbol, lambda: _alpaca_loader(record, as_of=as_of, history_days=history_days))
        add("tradier", "us_equity_history", "markets/history", record.symbol, lambda: tradier.daily_history(record.symbol, as_of=as_of, history_days=history_days), configured=tradier.configured)
        add("massive", "us_equity_history", "stocks-aggs", record.symbol, lambda: massive.daily_history("stock", record.symbol, as_of=as_of, history_days=history_days), configured=massive.configured)
        add("twelve_data", "us_equity_history", "time_series", record.symbol, lambda: twelve.daily_history((record.symbol,), as_of=as_of, history_days=history_days)[1], configured=twelve.configured)
        add("yahoo", "us_equity_history", "chart", record.provider_symbol, yahoo, authenticated=True)
    elif record.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        add("eodhd", "international_equity_history", "eodhd-history", eod_record.provider_symbol, eod, configured=eodhd_provider.configured)
        add("twelve_data", "international_equity_history", "time_series", record.provider_symbol, lambda: twelve.daily_history((record.provider_symbol, record.symbol), as_of=as_of, history_days=history_days)[1], configured=twelve.configured)
        add("yahoo", "international_equity_history", "chart", record.provider_symbol, yahoo, authenticated=True)
    elif record.asset_class is CandidateAssetClass.FX:
        add("twelve_data", "fx_history", "time_series", record.provider_symbol, lambda: twelve.daily_history((record.provider_symbol, record.symbol), as_of=as_of, history_days=history_days)[1], configured=twelve.configured)
        add("massive", "fx_history", "forex-aggs", record.symbol, lambda: massive.daily_history("fx", record.symbol, as_of=as_of, history_days=history_days), configured=massive.configured)
        add("eodhd", "fx_history", "eodhd-history", eod_record.provider_symbol, eod, configured=eodhd_provider.configured)
        add("yahoo", "fx_history", "chart", record.provider_symbol, yahoo, authenticated=True)
    elif record.asset_class is CandidateAssetClass.CRYPTO:
        binding = _crypto_binding(record)
        alpaca_symbol = _alpaca_crypto_symbol(record, binding)
        rows = tuple(alpaca_crypto_rows.get(alpaca_symbol, ()))
        if rows:
            add("alpaca", "crypto_history", _ALPACA_CRYPTO_DATASET, alpaca_symbol, lambda rows=rows: rows, authenticated=True)
        if binding is not None:
            cb = str(binding.get("coinbase_product_id") or "")
            kr = str(binding.get("kraken_symbol") or "")
            if cb:
                add("coinbase", "crypto_history", "exchange-candles", cb, lambda: coinbase.daily_history(cb, as_of=as_of, history_days=history_days), authenticated=True)
            if kr:
                add("kraken", "crypto_history", "spot-ohlc", kr, lambda: kraken.daily_history(kr, as_of=as_of, history_days=history_days), authenticated=True)
        add("massive", "crypto_history", "crypto-aggs", record.symbol, lambda: massive.daily_history("crypto", record.symbol, as_of=as_of, history_days=history_days), configured=massive.configured)
        add("twelve_data", "crypto_history", "time_series", record.provider_symbol, lambda: twelve.daily_history((record.provider_symbol, record.symbol), as_of=as_of, history_days=history_days)[1], configured=twelve.configured)
        add("yahoo", "crypto_history", "chart", record.provider_symbol, yahoo, authenticated=True)
    elif record.asset_class is CandidateAssetClass.FUTURE:
        massive_symbol = _massive_future_symbol(record.symbol)
        add("massive", "futures_history", "futures-aggs", massive_symbol, lambda: massive.daily_history("future", massive_symbol, as_of=as_of, history_days=history_days), configured=massive.configured)
        if record.provider_kind == "yahoo" and "=" not in record.provider_symbol:
            add("yahoo", "futures_history", "chart-exact", record.provider_symbol, yahoo, authenticated=True)
    elif record.asset_class is CandidateAssetClass.FIXED_INCOME:
        if record.provider_kind == "eodhd" and bool(record.instrument_identifier):
            add("eodhd", "fixed_income_exact_security_history", "eodhd-history", eod_record.provider_symbol, eod, configured=eodhd_provider.configured, fixed_income=True)
    return tuple(candidates)


def _corroborate_options(records, features, *, as_of, tradier):
    result = dict(features)
    ledger = current_redundancy_ledger()
    key = ProviderCapabilityKey("tradier", "active_option_chain_validation", "options/chains")
    if ledger is not None:
        ledger.declare(key, configured=tradier.configured, authenticated=False, routed=True, certified_for_evidence_role=True)
    grouped: dict[tuple[str, date], list] = {}
    for record in records:
        if record.asset_class is CandidateAssetClass.OPTION and record.underlying_symbol and record.expiration_at is not None:
            grouped.setdefault((record.underlying_symbol, record.expiration_at.date()), []).append(record)
    for (underlying, expiration), option_records in grouped.items():
        if not tradier.configured:
            break
        if ledger is not None:
            ledger.attempted(key)
        try:
            chain = tradier.active_option_chain(underlying, expiration, as_of=as_of)
        except TradierMarketDataError:
            if ledger is not None:
                ledger.failed(key, "provider_evidence_unavailable")
            continue
        by_symbol = {item.option_symbol.replace(" ", ""): item for item in chain}
        used = []
        for record in option_records:
            evidence = by_symbol.get(record.provider_symbol.replace(" ", "").replace("O:", ""))
            existing = result.get(record.symbol)
            if evidence is None or existing is None:
                continue
            used.append(evidence.source_identifier)
            result[record.symbol] = replace(existing, evidence_identifiers=tuple(dict.fromkeys((*existing.evidence_identifiers, evidence.source_identifier))))
        if used and ledger is not None:
            ledger.used(key, source_identifiers=tuple(dict.fromkeys(used)), failed_over=False)
    return result


def _mark_existing_result_usage(records, features):
    ledger = current_redundancy_ledger()
    if ledger is None:
        return
    for record in records:
        feature = features.get(record.symbol)
        if feature is None:
            continue
        sources = tuple(feature.evidence_identifiers)
        if record.asset_class is CandidateAssetClass.OPTION:
            providers = tuple(p for p in ("alpaca_indicative", "tradier", "massive") if any(p in source.lower() for source in sources))
            if not providers and record.provider_kind in {"alpaca_indicative", "tradier", "massive"}:
                providers = (record.provider_kind,)
            for provider in providers:
                dataset = {"alpaca_indicative": "ALPACA.OPTIONS.INDICATIVE", "tradier": "markets/history", "massive": "OPRA"}[provider]
                key = ProviderCapabilityKey(provider, "option_evidence", dataset)
                ledger.declare(key, configured=True, authenticated=True, routed=True, certified_for_evidence_role=True)
                ledger.used(key, source_identifiers=tuple(s for s in sources if provider in s.lower()), failed_over=provider != "alpaca_indicative")
            continue
        capability = {
            CandidateAssetClass.US_EQUITY: "us_equity_history",
            CandidateAssetClass.US_ETF: "us_equity_history",
            CandidateAssetClass.INTERNATIONAL_EQUITY: "international_equity_history",
            CandidateAssetClass.FX: "fx_history",
            CandidateAssetClass.CRYPTO: "crypto_history",
            CandidateAssetClass.FUTURE: "futures_history",
            CandidateAssetClass.FIXED_INCOME: "fixed_income_exact_security_history",
        }.get(record.asset_class)
        provider = record.provider_kind.strip().lower()
        if not provider or capability is None or provider == "unbound":
            continue
        dataset = record.provider_dataset or {"alpaca": "IEX", "eodhd": "eodhd-history", "yahoo": "chart", "massive": "market-aggs"}.get(provider, "provider-native")
        key = ProviderCapabilityKey(provider, capability, dataset)
        ledger.declare(key, configured=True, authenticated=True, routed=True, certified_for_evidence_role=True)
        ledger.used(key, source_identifiers=sources, failed_over=False)


def _prefetch_alpaca_crypto(missing, *, as_of, policy, provider):
    crypto = tuple(r for r in missing if r.asset_class is CandidateAssetClass.CRYPTO)
    if not crypto or not provider.configured:
        return {}
    symbols = tuple(dict.fromkeys(_alpaca_crypto_symbol(r, _crypto_binding(r)) for r in crypto))
    ledger = current_redundancy_ledger()
    key = ProviderCapabilityKey("alpaca", "crypto_history", _ALPACA_CRYPTO_DATASET)
    if ledger is not None:
        ledger.declare(key, configured=True, authenticated=False, routed=True, certified_for_evidence_role=True)
        ledger.attempted(key)
    try:
        rows = provider.daily_history_many(symbols, as_of=as_of, history_days=policy.history_days)
    except AlpacaCryptoHistoryError as error:
        if ledger is not None:
            ledger.failed(key, "rate_limit" if getattr(error, "status_code", None) == 429 else "provider_evidence_unavailable")
        return {}
    used = tuple(f"alpaca-crypto-batch:{symbol}:rows={len(values)}" for symbol, values in rows.items() if values)
    if used and ledger is not None:
        ledger.used(key, source_identifiers=used, failed_over=False)
    return rows


def default_redundant_market_probe(records, as_of, policy, *, http_get=requests.get):
    timestamp = _legacy._aware(as_of, field_name="as_of")
    if current_redundancy_ledger() is None:
        begin_redundancy_cycle(f"cio-market-evidence:{timestamp.isoformat()}", timestamp)

    primary_records = tuple(_primary_probe_record(record) for record in records)
    result = dict(_legacy.default_market_probe(primary_records, timestamp, policy, http_get=http_get))
    _mark_existing_result_usage(primary_records, result)
    missing = tuple(r for r in records if r.symbol not in result and r.asset_class is not CandidateAssetClass.OPTION)

    if missing:
        eodhd = _legacy.build_eodhd_provider()
        tradier = TradierMarketDataProvider()
        massive = MassiveMultiAssetProvider()
        twelve = TwelveDataHistoryProvider()
        coinbase = CoinbaseHistoryProvider()
        kraken = KrakenHistoryProvider()
        alpaca_crypto_rows = _prefetch_alpaca_crypto(missing, as_of=timestamp, policy=policy, provider=AlpacaCryptoHistoryProvider(http_get=http_get))
        router = RedundantMarketHistoryRouter()
        ledger = current_redundancy_ledger()
        for record in missing:
            candidates = _candidate_set(record, as_of=timestamp, policy=policy, http_get=http_get, eodhd_provider=eodhd, tradier=tradier, massive=massive, twelve=twelve, coinbase=coinbase, kraken=kraken, alpaca_crypto_rows=alpaca_crypto_rows)
            if ledger is not None:
                for candidate in candidates:
                    ledger.declare(candidate.key, configured=candidate.configured, authenticated=candidate.authenticated, routed=True, certified_for_evidence_role=candidate.certified_for_evidence_role)
            if not candidates:
                continue
            try:
                routed = router.fetch(candidates, as_of=timestamp, minimum_rows=policy.minimum_history_bars)
            except RedundantMarketHistoryError:
                continue
            result[record.symbol] = _feature_from_rows(record, routed.rows, routed.evidence_identifiers)

    return _corroborate_options(records, result, as_of=timestamp, tradier=TradierMarketDataProvider())
