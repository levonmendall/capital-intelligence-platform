"""Verify and persist connectivity for every configured free public provider."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Sequence

import requests

from data import MarketDataQuery
from providers.crypto_venues import (
    CoinbaseExchangeProvider,
    CryptoVenueBindingRegistry,
    KrakenSpotProvider,
)
from providers.free_connections import (
    FreeProviderConnectionError,
    FreeProviderConnectionVerifier,
    SQLiteFreeProviderConnectionStore,
    load_free_provider_catalog,
)


class _CoinbaseConnectivityResponse:
    """Hide optional exchange time from the non-authoritative health adapter."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.status_code = int(getattr(response, "status_code", 0))

    def json(self) -> Any:
        payload = self._response.json()
        if not isinstance(payload, dict):
            return payload
        normalized = dict(payload)
        normalized.pop("time", None)
        return normalized


class CoinbaseConnectivityProbeProvider:
    """Use the probe cutoff for Coinbase connectivity timestamps.

    Coinbase's public level-one response may omit a timestamp or publish one a few
    milliseconds after a health query begins. The canonical provider must reject
    that condition for point-in-time investment evidence. This runner-only wrapper
    deliberately removes the optional source timestamp and freezes the fallback to
    the connectivity-query cutoff. Connection reports remain non-authoritative and
    cannot enter decision, readiness, execution, or real-money paths.
    """

    def __init__(
        self,
        *,
        bindings: CryptoVenueBindingRegistry,
        timeout: int = 15,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self._bindings = bindings
        self._timeout = timeout
        self._http_get = http_get or requests.get

    def fetch(self, query: MarketDataQuery):
        if not isinstance(query, MarketDataQuery):
            raise TypeError("query must be MarketDataQuery")

        def health_get(*args: Any, **kwargs: Any) -> _CoinbaseConnectivityResponse:
            return _CoinbaseConnectivityResponse(self._http_get(*args, **kwargs))

        provider = CoinbaseExchangeProvider(
            bindings=self._bindings,
            timeout=self._timeout,
            clock=lambda: query.as_of,
            http_get=health_get,
        )
        return provider.fetch(query)


class _KrakenConnectivityResponse:
    """Hide publication timestamps from the non-authoritative health adapter."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.status_code = int(getattr(response, "status_code", 0))

    def json(self) -> Any:
        payload = self._response.json()
        if not isinstance(payload, dict):
            return payload
        normalized = dict(payload)
        result = normalized.get("result")
        if not isinstance(result, dict):
            return normalized
        normalized_result = dict(result)
        for side in ("bids", "asks"):
            rows = normalized_result.get(side)
            if not isinstance(rows, list):
                continue
            normalized_rows: list[Any] = []
            for row in rows:
                if isinstance(row, dict):
                    normalized_row = dict(row)
                    normalized_row.pop("publication_ts", None)
                    normalized_rows.append(normalized_row)
                else:
                    normalized_rows.append(row)
            normalized_result[side] = normalized_rows
        normalized["result"] = normalized_result
        return normalized


class KrakenConnectivityProbeProvider:
    """Use the probe cutoff for Kraken connectivity timestamps.

    Kraken's public pre-trade response can be stamped while the HTTP request is in
    flight. A report-wide cutoff captured before the request can therefore precede
    the returned publication timestamp by a few seconds even though the response is
    valid live connectivity evidence. The canonical Kraken provider intentionally
    remains strict for point-in-time investment evidence. This runner-only adapter
    removes publication timestamps and freezes the fallback/retrieval clock to the
    connectivity-query cutoff so a health check is not rejected solely because its
    response arrived after the report started. Connection evidence remains
    non-authoritative and grants no readiness, execution, or real-money authority.
    """

    def __init__(
        self,
        *,
        bindings: CryptoVenueBindingRegistry,
        timeout: int = 15,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self._bindings = bindings
        self._timeout = timeout
        self._http_get = http_get or requests.get

    def fetch(self, query: MarketDataQuery):
        if not isinstance(query, MarketDataQuery):
            raise TypeError("query must be MarketDataQuery")

        def health_get(*args: Any, **kwargs: Any) -> _KrakenConnectivityResponse:
            return _KrakenConnectivityResponse(self._http_get(*args, **kwargs))

        provider = KrakenSpotProvider(
            bindings=self._bindings,
            timeout=self._timeout,
            clock=lambda: query.as_of,
            http_get=health_get,
        )
        return provider.fetch(query)


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_FREE_PROVIDER_CATALOG",
            "config/free_provider_connections.json",
        ),
    )
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_FREE_PROVIDER_DATABASE",
            str(data_dir / "free_provider_connections.db"),
        ),
    )
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument(
        "--require-all-connected",
        action="store_true",
        help="Return a blocking status unless every enabled service is connected.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SQLiteFreeProviderConnectionStore(args.database)
    try:
        if args.status:
            report = store.latest()
            print(
                json.dumps(
                    {
                        "status": "unavailable" if report is None else "available",
                        "report": None if report is None else report.to_dict(),
                    },
                    sort_keys=True,
                )
            )
            return 0 if report is not None else 2

        catalog = load_free_provider_catalog(args.catalog)
        report = FreeProviderConnectionVerifier(
            catalog,
            repository_root=args.repository_root,
            coinbase_factory=CoinbaseConnectivityProbeProvider,
            kraken_factory=KrakenConnectivityProbeProvider,
        ).verify()
        sequence = None if args.no_persist else store.append(report)
        print(
            json.dumps(
                {
                    "sequence": sequence,
                    "report": report.to_dict(),
                },
                sort_keys=True,
            )
        )
        if args.require_all_connected and not report.all_enabled_connected:
            return 3
        return 0
    except (OSError, TypeError, ValueError, FreeProviderConnectionError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "provider_certification_granted": False,
                    "paper_test_readiness_granted": False,
                    "execution_authority_granted": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
