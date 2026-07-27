"""EODHD multi-asset evidence provider.

This adapter intentionally distinguishes broad analytical coverage from execution
quality.  It normalizes end-of-day bars and historical dividends/splits into the
canonical market contracts, while retaining fundamentals, symbol directories,
bonds, commodities, and other vendor-native responses as immutable raw dataset
snapshots for later governed normalization.

The adapter does not manufacture bid/ask quotes from OHLC values and does not
claim that a current or delisted symbol list is a complete historical security
master.  Existing provider-certification and all-markets data-readiness gates
remain authoritative.
"""

from __future__ import annotations

import json
import os
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from data.market import (
    BarInterval,
    CanonicalMarketDataProvider,
    CorporateAction,
    CorporateActionType,
    MarketDataBatch,
    MarketDataProvenance,
    MarketDataQuery,
    MarketDataType,
    PriceBar,
)
from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetError,
    ProviderDatasetProvider,
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)


EODHD_API_BASE = "https://eodhd.com/api"
EODHD_SOURCE_VERSION = "eodhd-rest.v1"


class EODHDProviderError(ProviderDatasetError):
    """Raised when EODHD cannot return a valid governed response."""


@dataclass(frozen=True, slots=True)
class EODHDRetrievalPolicy:
    """Bounded retry policy for EODHD REST retrieval."""

    max_attempts: int = 3
    backoff_seconds: float = 0.25
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(
            self.max_attempts, int
        ):
            raise TypeError("max_attempts must be an integer")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if isinstance(self.backoff_seconds, bool) or not isinstance(
            self.backoff_seconds, (int, float)
        ):
            raise TypeError("backoff_seconds must be numeric")
        if float(self.backoff_seconds) < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if not self.retry_statuses:
            raise ValueError("retry_statuses cannot be empty")


@dataclass(frozen=True, slots=True)
class EODHDInstrumentBinding:
    """Map one stable internal instrument identity to an EODHD symbol."""

    instrument_id: str
    provider_symbol: str
    venue: str
    currency: str

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "provider_symbol",
            "venue",
            "currency",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot be empty")
            if field_name != "instrument_id":
                normalized = normalized.upper()
            object.__setattr__(self, field_name, normalized)


class EODHDBindingRegistry:
    """Immutable lookup from canonical instrument ID to provider symbol."""

    def __init__(self, bindings: tuple[EODHDInstrumentBinding, ...]) -> None:
        if not isinstance(bindings, tuple):
            raise TypeError("bindings must be a tuple")
        if not all(isinstance(item, EODHDInstrumentBinding) for item in bindings):
            raise TypeError("bindings must contain EODHDInstrumentBinding values")
        by_instrument: dict[str, EODHDInstrumentBinding] = {}
        provider_keys: set[tuple[str, str]] = set()
        for binding in bindings:
            if binding.instrument_id in by_instrument:
                raise ValueError(
                    f"duplicate EODHD instrument binding: {binding.instrument_id}"
                )
            provider_key = (binding.venue, binding.provider_symbol)
            if provider_key in provider_keys:
                raise ValueError(
                    "duplicate EODHD venue-symbol binding: "
                    f"{binding.venue}:{binding.provider_symbol}"
                )
            by_instrument[binding.instrument_id] = binding
            provider_keys.add(provider_key)
        self._bindings = by_instrument

    def resolve(self, instrument_id: str) -> EODHDInstrumentBinding:
        if not isinstance(instrument_id, str) or not instrument_id.strip():
            raise ValueError("instrument_id cannot be empty")
        try:
            return self._bindings[instrument_id.strip()]
        except KeyError as error:
            raise EODHDProviderError(
                f"no EODHD binding exists for instrument {instrument_id!r}"
            ) from error

    @property
    def bindings(self) -> tuple[EODHDInstrumentBinding, ...]:
        return tuple(self._bindings.values())


class EODHDProvider(CanonicalMarketDataProvider, ProviderDatasetProvider):
    """Retrieve broad paper-test evidence from the EODHD REST API."""

    def __init__(
        self,
        api_token: str | None = None,
        *,
        bindings: EODHDBindingRegistry | None = None,
        timeout: int = 30,
        clock: Callable[[], datetime] | None = None,
        http_get: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        retrieval_policy: EODHDRetrievalPolicy | None = None,
    ) -> None:
        self.api_token = (
            api_token
            or os.getenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN")
            or os.getenv("EODHD_API_TOKEN")
        )
        self.bindings = bindings or EODHDBindingRegistry(())
        self.timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._http_get = http_get or requests.get
        self._sleeper = sleeper or time_module.sleep
        self._policy = retrieval_policy or EODHDRetrievalPolicy()

    @property
    def name(self) -> str:
        return "EODHD"

    @property
    def configured(self) -> bool:
        return bool(self.api_token)

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        """Return canonical daily bars or historical corporate actions.

        EODHD's ordinary REST live endpoint exposes latest OHLCV values rather
        than a complete bid/ask book.  QUOTE, TRADE, funding-rate, and open-
        interest requests therefore fail closed instead of being fabricated.
        """

        if not isinstance(query, MarketDataQuery):
            raise TypeError("query must be MarketDataQuery")
        binding = self.bindings.resolve(query.instrument_id)
        if query.venue is not None and query.venue != binding.venue:
            raise EODHDProviderError(
                "query venue does not match the configured EODHD binding"
            )
        if query.data_type is MarketDataType.BAR:
            return self._fetch_bars(query, binding)
        if query.data_type is MarketDataType.CORPORATE_ACTION:
            return self._fetch_corporate_actions(query, binding)
        raise EODHDProviderError(
            "EODHD adapter supports only daily bars and historical corporate "
            "actions; it does not fabricate quotes or execution liquidity"
        )

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        """Return an immutable raw dataset snapshot for governed normalization."""

        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        retrieved_at = self._now()
        dataset_type = query.dataset_type
        limitations: tuple[str, ...]
        if dataset_type is ProviderDatasetType.ACCOUNT_ENTITLEMENT:
            payload = self._request("/user", resource="account entitlement")
            limitations = (
                "entitlement response proves API access, not dataset licensing approval",
            )
        elif dataset_type is ProviderDatasetType.EXCHANGE_DIRECTORY:
            payload = self._request(
                "/exchanges-list/",
                resource="exchange directory",
            )
            limitations = (
                "provider exchange coverage requires independent reconciliation",
            )
        elif dataset_type is ProviderDatasetType.SYMBOL_DIRECTORY:
            payload = {
                "active": self._request(
                    f"/exchange-symbol-list/{query.provider_symbol}",
                    params={"delisted": 0},
                    resource=f"active symbol directory {query.provider_symbol}",
                ),
                "delisted": self._request(
                    f"/exchange-symbol-list/{query.provider_symbol}",
                    params={"delisted": 1},
                    resource=f"delisted symbol directory {query.provider_symbol}",
                ),
            }
            limitations = (
                "current and delisted symbol lists do not establish complete historical identifier lineage",
                "venue and symbol changes require a separately certified security-master history",
            )
        elif dataset_type is ProviderDatasetType.FUNDAMENTALS:
            payload = self._request(
                f"/v1.1/fundamentals/{query.provider_symbol}",
                resource=f"fundamentals {query.provider_symbol}",
            )
            limitations = (
                "vendor-native fundamentals require downstream field normalization",
                "point-in-time statement availability must be reconciled before decision use",
            )
        elif dataset_type is ProviderDatasetType.FIXED_INCOME:
            payload = self._history_payload(query)
            limitations = (
                "fixed-income coverage and evaluated-pricing methodology require asset-specific certification",
            )
        elif dataset_type is ProviderDatasetType.COMMODITY:
            parameters = self._range_parameters(query)
            parameters["interval"] = "daily"
            payload = self._request(
                f"/commodities/historical/{query.provider_symbol}",
                params=parameters,
                resource=f"commodity history {query.provider_symbol}",
            )
            limitations = (
                "commodity series are analytical evidence and not a futures execution feed",
            )
        elif dataset_type is ProviderDatasetType.MARKET_HISTORY:
            payload = self._history_payload(query)
            limitations = (
                "end-of-day OHLCV does not provide bid/ask execution liquidity",
            )
        elif dataset_type is ProviderDatasetType.CORPORATE_ACTIONS:
            parameters = self._range_parameters(query)
            payload = {
                "dividends": self._request(
                    f"/div/{query.provider_symbol}",
                    params=parameters,
                    resource=f"dividends {query.provider_symbol}",
                ),
                "splits": self._request(
                    f"/splits/{query.provider_symbol}",
                    params=parameters,
                    resource=f"splits {query.provider_symbol}",
                ),
            }
            limitations = (
                "actions without declaration timestamps use retrieval-time availability",
                "mergers, spinoffs, symbol changes, and delistings require the historical security master",
            )
        else:  # pragma: no cover - enum exhaustiveness safeguard
            raise EODHDProviderError(
                f"unsupported EODHD dataset type: {dataset_type.value}"
            )
        payload = self._bounded_payload(payload, query.limit)
        observed_at = self._payload_observed_at(payload, fallback=retrieved_at)
        if observed_at > retrieved_at:
            observed_at = retrieved_at
        return ProviderDatasetSnapshot(
            query=query,
            provider=self.name,
            source_version=EODHD_SOURCE_VERSION,
            observed_at=observed_at,
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
            quality_state=DataQualityState.LIVE,
            availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            payload=payload,
            provider_record_id=(
                f"eodhd:{dataset_type.value}:{query.provider_symbol}:"
                f"{retrieved_at.isoformat()}"
            ),
            limitations=limitations,
        )

    def _fetch_bars(
        self,
        query: MarketDataQuery,
        binding: EODHDInstrumentBinding,
    ) -> MarketDataBatch:
        if query.interval is not BarInterval.DAY:
            raise EODHDProviderError(
                "EODHD canonical adapter supports only daily EOD bars"
            )
        parameters: dict[str, object] = {
            "period": "d",
            "order": "a",
            "to": query.as_of.date().isoformat(),
        }
        if query.start_at is not None:
            parameters["from"] = query.start_at.date().isoformat()
        payload = self._request(
            f"/eod/{binding.provider_symbol}",
            params=parameters,
            resource=f"EOD history {binding.provider_symbol}",
        )
        if not isinstance(payload, list):
            raise EODHDProviderError("EOD history response must be a JSON array")
        retrieved_at = self._now()
        records: list[PriceBar] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            bar_date = self._date(item.get("date"), field_name="date")
            start_at = datetime.combine(bar_date, time.min, tzinfo=timezone.utc)
            end_at = start_at + timedelta(days=1)
            if end_at > query.as_of or end_at > retrieved_at:
                continue
            try:
                record = PriceBar(
                    instrument_id=binding.instrument_id,
                    currency=binding.currency,
                    interval=BarInterval.DAY,
                    start_at=start_at,
                    end_at=end_at,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume") or 0.0),
                    provenance=MarketDataProvenance(
                        provider=self.name,
                        venue=binding.venue,
                        observed_at=end_at,
                        retrieved_at=retrieved_at,
                        quality_state=DataQualityState.LIVE,
                        provider_record_id=(
                            f"{binding.provider_symbol}:{bar_date.isoformat()}"
                        ),
                    ),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise EODHDProviderError(
                    f"invalid EOD bar for {binding.provider_symbol} on {bar_date}"
                ) from error
            records.append(record)
        records = records[-query.limit :]
        return MarketDataBatch(query=query, records=tuple(records))

    def _fetch_corporate_actions(
        self,
        query: MarketDataQuery,
        binding: EODHDInstrumentBinding,
    ) -> MarketDataBatch:
        parameters: dict[str, object] = {
            "to": query.as_of.date().isoformat(),
        }
        if query.start_at is not None:
            parameters["from"] = query.start_at.date().isoformat()
        dividends = self._request(
            f"/div/{binding.provider_symbol}",
            params=parameters,
            resource=f"dividends {binding.provider_symbol}",
        )
        splits = self._request(
            f"/splits/{binding.provider_symbol}",
            params=parameters,
            resource=f"splits {binding.provider_symbol}",
        )
        if not isinstance(dividends, list) or not isinstance(splits, list):
            raise EODHDProviderError(
                "corporate-action responses must be JSON arrays"
            )
        retrieved_at = self._now()
        records: list[CorporateAction] = []
        for item in dividends:
            if not isinstance(item, dict):
                continue
            effective_date = self._date(item.get("date"), field_name="date")
            effective_at = datetime.combine(
                effective_date, time.min, tzinfo=timezone.utc
            )
            declaration = self._optional_date(item.get("declarationDate"))
            observed_at = (
                datetime.combine(declaration, time.min, tzinfo=timezone.utc)
                if declaration is not None
                else effective_at
            )
            if observed_at > query.as_of or observed_at > retrieved_at:
                continue
            currency = str(item.get("currency") or binding.currency).upper()
            try:
                amount = float(item.get("value"))
            except (TypeError, ValueError) as error:
                raise EODHDProviderError(
                    f"invalid dividend amount for {binding.provider_symbol}"
                ) from error
            records.append(
                CorporateAction(
                    instrument_id=binding.instrument_id,
                    currency=currency,
                    action_type=CorporateActionType.CASH_DIVIDEND,
                    effective_at=effective_at,
                    amount=amount,
                    provenance=MarketDataProvenance(
                        provider=self.name,
                        venue=binding.venue,
                        observed_at=observed_at,
                        retrieved_at=retrieved_at,
                        quality_state=DataQualityState.LIVE,
                        provider_record_id=(
                            f"{binding.provider_symbol}:dividend:"
                            f"{effective_date.isoformat()}"
                        ),
                    ),
                )
            )
        for item in splits:
            if not isinstance(item, dict):
                continue
            effective_date = self._date(item.get("date"), field_name="date")
            effective_at = datetime.combine(
                effective_date, time.min, tzinfo=timezone.utc
            )
            if effective_at > query.as_of or effective_at > retrieved_at:
                continue
            ratio = self._split_ratio(item.get("split") or item.get("value"))
            records.append(
                CorporateAction(
                    instrument_id=binding.instrument_id,
                    currency=binding.currency,
                    action_type=(
                        CorporateActionType.REVERSE_SPLIT
                        if ratio < 1.0
                        else CorporateActionType.SPLIT
                    ),
                    effective_at=effective_at,
                    ratio=ratio,
                    provenance=MarketDataProvenance(
                        provider=self.name,
                        venue=binding.venue,
                        observed_at=effective_at,
                        retrieved_at=retrieved_at,
                        quality_state=DataQualityState.LIVE,
                        provider_record_id=(
                            f"{binding.provider_symbol}:split:"
                            f"{effective_date.isoformat()}"
                        ),
                    ),
                )
            )
        records.sort(
            key=lambda item: (
                item.provenance.observed_at,
                item.effective_at,
                item.action_type.value,
            )
        )
        return MarketDataBatch(query=query, records=tuple(records[-query.limit :]))

    def _history_payload(self, query: ProviderDatasetQuery) -> Any:
        parameters = self._range_parameters(query)
        parameters.update({"period": "d", "order": "a"})
        return self._request(
            f"/eod/{query.provider_symbol}",
            params=parameters,
            resource=f"history {query.provider_symbol}",
        )

    def _range_parameters(
        self, query: ProviderDatasetQuery
    ) -> dict[str, object]:
        parameters: dict[str, object] = {
            "to": (query.end_at or query.as_of).date().isoformat(),
        }
        if query.start_at is not None:
            parameters["from"] = query.start_at.date().isoformat()
        return parameters

    def _request(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        resource: str,
    ) -> Any:
        if not self.api_token:
            raise EODHDProviderError(
                "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN is not configured"
            )
        parameters = dict(params or {})
        parameters["api_token"] = self.api_token
        parameters.setdefault("fmt", "json")
        url = EODHD_API_BASE + path
        last_error: Exception | None = None
        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                response = self._http_get(
                    url,
                    params=parameters,
                    timeout=self.timeout,
                )
                status_code = int(getattr(response, "status_code", 0))
                if status_code in self._policy.retry_statuses:
                    raise EODHDProviderError(
                        f"temporary EODHD HTTP {status_code} for {resource}"
                    )
                if status_code < 200 or status_code >= 300:
                    raise EODHDProviderError(
                        f"EODHD HTTP {status_code} for {resource}"
                    )
                payload = response.json()
                if isinstance(payload, dict) and payload.get("error"):
                    raise EODHDProviderError(
                        f"EODHD rejected {resource}: {payload.get('error')}"
                    )
                if not isinstance(payload, (dict, list)):
                    raise EODHDProviderError(
                        f"EODHD returned non-JSON data for {resource}"
                    )
                return payload
            except (requests.RequestException, ValueError, EODHDProviderError) as error:
                last_error = error
                if attempt >= self._policy.max_attempts:
                    break
                self._sleeper(
                    float(self._policy.backoff_seconds) * (2 ** (attempt - 1))
                )
        raise EODHDProviderError(
            f"unable to retrieve {resource} from EODHD"
        ) from last_error

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _date(value: object, *, field_name: str) -> date:
        if not isinstance(value, str) or not value.strip():
            raise EODHDProviderError(f"{field_name} must be an ISO date")
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as error:
            raise EODHDProviderError(
                f"{field_name} must be an ISO date"
            ) from error

    @staticmethod
    def _optional_date(value: object) -> date | None:
        if value in (None, "", "0000-00-00"):
            return None
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None

    @staticmethod
    def _split_ratio(value: object) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            ratio = float(value)
        elif isinstance(value, str):
            text = value.strip()
            separator = "/" if "/" in text else ":" if ":" in text else None
            if separator is None:
                ratio = float(text)
            else:
                numerator, denominator = text.split(separator, 1)
                ratio = float(numerator) / float(denominator)
        else:
            raise EODHDProviderError("split ratio is invalid")
        if ratio <= 0:
            raise EODHDProviderError("split ratio must be positive")
        return ratio

    @staticmethod
    def _bounded_payload(payload: Any, limit: int) -> dict[str, Any] | list[Any]:
        if isinstance(payload, list):
            return payload[-limit:]
        if isinstance(payload, dict):
            return payload
        raise EODHDProviderError("provider payload must be a JSON object or array")

    @classmethod
    def _payload_observed_at(
        cls,
        payload: dict[str, Any] | list[Any],
        *,
        fallback: datetime,
    ) -> datetime:
        candidates: list[date] = []
        values = payload if isinstance(payload, list) else [payload]
        for item in values:
            if not isinstance(item, dict):
                continue
            for key in ("date", "updated_at", "updatedAt"):
                candidate = cls._optional_date(item.get(key))
                if candidate is not None:
                    candidates.append(candidate)
        if not candidates:
            return fallback
        observed = datetime.combine(max(candidates), time.min, tzinfo=timezone.utc)
        return observed if observed <= fallback else fallback


def load_eodhd_bindings(path: str | Path) -> EODHDBindingRegistry:
    """Load a secret-free internal-to-provider symbol mapping."""

    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EODHDProviderError(
            f"cannot load EODHD binding file {str(source)!r}"
        ) from error
    if not isinstance(payload, dict):
        raise EODHDProviderError("EODHD binding file must be a JSON object")
    if payload.get("schema_version") != "eodhd-instrument-bindings.v1":
        raise EODHDProviderError("unsupported EODHD binding schema")
    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, list):
        raise EODHDProviderError("bindings must be a JSON array")
    bindings = tuple(
        EODHDInstrumentBinding(
            instrument_id=str(item["instrument_id"]),
            provider_symbol=str(item["provider_symbol"]),
            venue=str(item["venue"]),
            currency=str(item["currency"]),
        )
        for item in raw_bindings
        if isinstance(item, dict)
    )
    if len(bindings) != len(raw_bindings):
        raise EODHDProviderError("every binding entry must be a JSON object")
    return EODHDBindingRegistry(bindings)


def build_eodhd_provider() -> EODHDProvider:
    """Deployment factory used by scheduled commands and certification tools."""

    binding_path = os.getenv("CAPITAL_INTELLIGENCE_EODHD_BINDINGS")
    registry = (
        EODHDBindingRegistry(())
        if not binding_path
        else load_eodhd_bindings(binding_path)
    )
    return EODHDProvider(bindings=registry)


__all__ = [
    "EODHDBindingRegistry",
    "EODHDInstrumentBinding",
    "EODHDProvider",
    "EODHDProviderError",
    "EODHDRetrievalPolicy",
    "build_eodhd_provider",
    "load_eodhd_bindings",
]
