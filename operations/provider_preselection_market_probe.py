"""Bounded single-pass market probe for provider preselection.

Provider preselection needs the same point-in-time historical feature contract as the
legacy market probe, but it must not amplify provider I/O. In particular, defined-risk
option call/put records share an underlying price history. This adapter fetches each
missing option-underlying Yahoo history once per probe, exposes it through the existing
Alpaca-history seam, and delegates feature construction to the certified legacy probe
with one bounded worker pool for non-crypto records.

Unresolved dated futures and crypto are the intentional extensions to that legacy path.
The configured futures catalog is provider-neutral, while crypto can originate from an
EODHD directory whose direct per-symbol history path is unnecessarily slow for provider
preselection. Crypto therefore bypasses that direct legacy probe and uses the existing
certified redundant crypto-history path (Alpaca, Coinbase, Kraken); unresolved futures
continue to use the redundant futures path. No synthetic factor is created: when the
redundant providers cannot return the governed minimum point-in-time history, the
instrument remains unresolved and publication stays fail-closed.

The adapter changes no catalog membership, ranking, evidence thresholds, CIO authority,
construction, execution, market scope, or paper-only controls. Missing provider evidence
remains fail closed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

import requests

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery_legacy as _legacy
from operations import redundant_market_probe as _redundant
from providers.alpaca_paper import (
    AlpacaPaperClient,
    AlpacaPaperProviderError,
    create_alpaca_paper_client,
)


_MAX_PROVIDER_IO_WORKERS = 4


def _usable_history(
    values: Sequence[Mapping[str, object]],
    *,
    as_of: datetime,
) -> bool:
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        observed = _legacy._timestamp(raw.get("t"))
        close = _legacy._number(raw.get("c"))
        if observed is not None and observed <= as_of and close > 0.0:
            return True
    return False


def _underlying_record(symbol: str) -> _legacy.DiscoveryCatalogRecord:
    return _legacy.DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=symbol,
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        economic_exposure="us_equity",
        venue="US",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="common_stock",
        provider_kind="yahoo",
        source_identifier=f"yahoo-chart:{symbol}",
    )


class _OptionUnderlyingHistoryClient:
    """Cache option-underlying history while preserving normal Alpaca batching."""

    def __init__(
        self,
        *,
        delegate: AlpacaPaperClient | None,
        option_underlyings: Sequence[str],
        http_get: Callable[..., Any],
        maximum_workers: int,
    ) -> None:
        self._delegate = delegate
        self._option_underlyings = frozenset(
            str(item).strip().upper() for item in option_underlyings if str(item).strip()
        )
        self._http_get = http_get
        self._maximum_workers = max(1, min(_MAX_PROVIDER_IO_WORKERS, maximum_workers))
        self._fallback_cache: dict[str, tuple[dict[str, object], ...]] = {}

    def historical_bars(
        self,
        symbols: Sequence[str],
        *,
        start: datetime,
        end: datetime,
        timeframe: str,
    ) -> Mapping[str, Sequence[Mapping[str, object]]]:
        requested = tuple(
            dict.fromkeys(
                str(item).strip().upper() for item in symbols if str(item).strip()
            )
        )
        result: dict[str, Sequence[Mapping[str, object]]] = {}
        if self._delegate is not None and requested:
            try:
                native = self._delegate.historical_bars(
                    requested,
                    start=start,
                    end=end,
                    timeframe=timeframe,
                )
            except (AlpacaPaperProviderError, OSError, TypeError, ValueError):
                native = {}
            for symbol, values in native.items():
                key = str(symbol).strip().upper()
                if key:
                    result[key] = values

        missing = tuple(
            symbol
            for symbol in requested
            if symbol in self._option_underlyings
            and not _usable_history(result.get(symbol, ()), as_of=end)
        )
        uncached = tuple(symbol for symbol in missing if symbol not in self._fallback_cache)
        history_days = max(1, (end - start).days)

        def fetch_yahoo(symbol: str) -> tuple[str, tuple[dict[str, object], ...]]:
            rows = _legacy._yahoo_rows(
                _underlying_record(symbol),
                as_of=end,
                history_days=history_days,
                http_get=self._http_get,
            )
            return symbol, rows

        if len(uncached) > 1 and self._maximum_workers > 1:
            with ThreadPoolExecutor(
                max_workers=min(self._maximum_workers, len(uncached)),
                thread_name_prefix="preselection-option-underlying",
            ) as executor:
                outcomes = tuple(executor.map(fetch_yahoo, uncached))
        else:
            outcomes = tuple(map(fetch_yahoo, uncached))
        for symbol, rows in outcomes:
            self._fallback_cache[symbol] = rows
        for symbol in missing:
            rows = self._fallback_cache.get(symbol, ())
            if rows:
                result[symbol] = rows
        return result


def _redundant_preselection_features(
    records: Sequence[_legacy.DiscoveryCatalogRecord],
    *,
    as_of: datetime,
    policy: _legacy.ComprehensiveMarketDiscoveryPolicy,
    http_get: Callable[..., Any],
    maximum_workers: int,
) -> Mapping[str, _legacy.DiscoveryMarketFeatures]:
    """Use certified redundant history without emitting deep-evidence stages."""

    unresolved = tuple(records)
    if not unresolved:
        return {}
    timestamp = _legacy._aware(as_of, field_name="as_of")
    core = _redundant._core
    alpaca_crypto_rows = core._prefetch_alpaca_crypto(
        unresolved,
        as_of=timestamp,
        policy=policy,
        provider=core.AlpacaCryptoHistoryProvider(http_get=http_get),
    )
    return _redundant._fetch_missing_concurrently(
        unresolved,
        timestamp=timestamp,
        policy=policy,
        http_get=http_get,
        eodhd=_legacy.build_eodhd_provider(),
        tradier=core.TradierMarketDataProvider(),
        massive=core.MassiveMultiAssetProvider(),
        twelve=core.TwelveDataHistoryProvider(),
        coinbase=core.CoinbaseHistoryProvider(),
        kraken=core.KrakenHistoryProvider(),
        alpaca_crypto_rows=alpaca_crypto_rows,
        already_processed=0,
        already_evidence_complete=0,
        decision_eligible_records=len(unresolved),
        maximum_workers=min(_MAX_PROVIDER_IO_WORKERS, maximum_workers),
        # Provider-preselection has its own governed progress stages. Reusing the deep
        # evidence worker must not make telemetry appear to enter deep analysis early.
        progress_callback=lambda *_args, **_kwargs: None,
    )


def default_provider_preselection_market_probe(
    records: Sequence[_legacy.DiscoveryCatalogRecord],
    as_of: datetime,
    policy: _legacy.ComprehensiveMarketDiscoveryPolicy,
    *,
    http_get: Callable[..., Any] = requests.get,
    alpaca_client: AlpacaPaperClient | None = None,
    maximum_workers: int = _MAX_PROVIDER_IO_WORKERS,
) -> Mapping[str, _legacy.DiscoveryMarketFeatures]:
    """Run bounded legacy probing plus certified redundant crypto/futures history."""

    if (
        isinstance(maximum_workers, bool)
        or not isinstance(maximum_workers, int)
        or maximum_workers < 1
    ):
        raise ValueError("maximum_workers must be a positive integer")
    ordered = tuple(records)
    legacy_records = tuple(
        record
        for record in ordered
        if record.asset_class is not CandidateAssetClass.CRYPTO
    )
    option_underlyings = tuple(
        dict.fromkeys(
            item.underlying_symbol.upper()
            for item in legacy_records
            if item.asset_class is CandidateAssetClass.OPTION and item.underlying_symbol
        )
    )
    delegate = alpaca_client
    if delegate is None:
        try:
            delegate = create_alpaca_paper_client()
        except (AlpacaPaperProviderError, OSError, TypeError, ValueError):
            delegate = None
    history_client = _OptionUnderlyingHistoryClient(
        delegate=delegate,
        option_underlyings=option_underlyings,
        http_get=http_get,
        maximum_workers=maximum_workers,
    )
    result = dict(
        _legacy.default_market_probe(
            legacy_records,
            as_of,
            policy,
            http_get=http_get,
            alpaca_client=history_client,
            maximum_workers=min(_MAX_PROVIDER_IO_WORKERS, maximum_workers),
        )
    )
    unresolved_redundant = tuple(
        record
        for record in ordered
        if record.symbol not in result
        and record.asset_class in (
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.FUTURE,
        )
    )
    if unresolved_redundant:
        result.update(
            _redundant_preselection_features(
                unresolved_redundant,
                as_of=as_of,
                policy=policy,
                http_get=http_get,
                maximum_workers=maximum_workers,
            )
        )
    return result


__all__ = ["default_provider_preselection_market_probe"]
