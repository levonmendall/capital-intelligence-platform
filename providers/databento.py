"""Native Databento HTTP ingestion for canonical and raw governed market data.

The adapter uses Databento's historical HTTP API with JSON Lines encoding so the
platform does not need the optional Databento client package.  Authentication,
record timestamps, raw provider payloads, and symbol mappings remain explicit.
Licensing and paper-allocation approval remain separate governance authorities.
"""

from __future__ import annotations

import hashlib
import json
import os
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from data.market import (
    BarInterval,
    CanonicalMarketDataProvider,
    MarketDataBatch,
    MarketDataProvenance,
    MarketDataQuery,
    MarketDataType,
    MarketQuote,
    MarketTrade,
    PriceBar,
    TradeSide,
)
from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetError,
    ProviderDatasetProvider,
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)


DATABENTO_HISTORICAL_BASE = "https://hist.databento.com/v0"
DATABENTO_SOURCE_VERSION = "databento-http-jsonl.v1"


class DatabentoProviderError(ProviderDatasetError):
    """Raised when Databento cannot return or normalize governed evidence."""


@dataclass(frozen=True, slots=True)
class DatabentoRetrievalPolicy:
    """Bounded retry policy for Databento HTTP requests."""

    max_attempts: int = 3
    backoff_seconds: float = 0.25
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
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
class DatabentoInstrumentBinding:
    """Map one stable platform instrument to a Databento dataset and symbol."""

    instrument_id: str
    dataset: str
    provider_symbol: str
    venue: str
    currency: str
    stype_in: str = "raw_symbol"

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "dataset",
            "provider_symbol",
            "venue",
            "currency",
            "stype_in",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot be empty")
            if field_name in {"dataset", "venue", "currency"}:
                normalized = normalized.upper()
            elif field_name == "stype_in":
                normalized = normalized.lower()
            object.__setattr__(self, field_name, normalized)
        if self.stype_in not in {"raw_symbol", "parent", "continuous", "instrument_id"}:
            raise ValueError("unsupported Databento input symbology")


class DatabentoBindingRegistry:
    """Immutable lookup of canonical instrument identities to Databento symbols."""

    def __init__(self, bindings: tuple[DatabentoInstrumentBinding, ...]) -> None:
        if not isinstance(bindings, tuple):
            raise TypeError("bindings must be a tuple")
        if not all(isinstance(item, DatabentoInstrumentBinding) for item in bindings):
            raise TypeError("bindings must contain DatabentoInstrumentBinding values")
        by_instrument: dict[str, DatabentoInstrumentBinding] = {}
        provider_keys: set[tuple[str, str, str]] = set()
        for binding in bindings:
            if binding.instrument_id in by_instrument:
                raise ValueError(
                    f"duplicate Databento instrument binding: {binding.instrument_id}"
                )
            provider_key = (binding.dataset, binding.stype_in, binding.provider_symbol)
            if provider_key in provider_keys:
                raise ValueError(
                    "duplicate Databento dataset/symbology/symbol binding: "
                    f"{binding.dataset}:{binding.stype_in}:{binding.provider_symbol}"
                )
            by_instrument[binding.instrument_id] = binding
            provider_keys.add(provider_key)
        self._bindings = by_instrument

    def resolve(self, instrument_id: str) -> DatabentoInstrumentBinding:
        if not isinstance(instrument_id, str) or not instrument_id.strip():
            raise ValueError("instrument_id cannot be empty")
        try:
            return self._bindings[instrument_id.strip()]
        except KeyError as error:
            raise DatabentoProviderError(
                f"no Databento binding exists for instrument {instrument_id!r}"
            ) from error

    @property
    def bindings(self) -> tuple[DatabentoInstrumentBinding, ...]:
        return tuple(self._bindings.values())


class DatabentoProvider(CanonicalMarketDataProvider, ProviderDatasetProvider):
    """Retrieve canonical and raw historical Databento evidence over HTTP."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        bindings: DatabentoBindingRegistry | None = None,
        timeout: int = 30,
        clock: Callable[[], datetime] | None = None,
        http_get: Callable[..., Any] | None = None,
        http_post: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        retrieval_policy: DatabentoRetrievalPolicy | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY")
            or os.getenv("DATABENTO_API_KEY")
        )
        self.bindings = bindings or DatabentoBindingRegistry(())
        self.timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._http_get = http_get or requests.get
        self._http_post = http_post or requests.post
        self._sleeper = sleeper or time_module.sleep
        self._policy = retrieval_policy or DatabentoRetrievalPolicy()

    @property
    def name(self) -> str:
        return "DATABENTO"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        if not isinstance(query, MarketDataQuery):
            raise TypeError("query must be MarketDataQuery")
        binding = self.bindings.resolve(query.instrument_id)
        if query.venue is not None and query.venue != binding.venue:
            raise DatabentoProviderError(
                "query venue does not match the configured Databento binding"
            )
        schema = self._schema_for_market_query(query)
        request_limit = query.limit * 5 if query.interval is BarInterval.FIVE_MINUTES else query.limit
        payload = self._timeseries(
            binding=binding,
            schema=schema,
            start=self._query_start(query),
            end=query.as_of,
            limit=min(request_limit, 100_000),
        )
        retrieved_at = self._now()
        if query.data_type is MarketDataType.QUOTE:
            records = self._normalize_quotes(payload, query, binding, retrieved_at)
        elif query.data_type is MarketDataType.TRADE:
            records = self._normalize_trades(payload, query, binding, retrieved_at)
        elif query.data_type is MarketDataType.BAR:
            minute_records = self._normalize_bars(payload, query, binding, retrieved_at)
            records = (
                self._aggregate_five_minute_bars(minute_records, query)
                if query.interval is BarInterval.FIVE_MINUTES
                else minute_records
            )
        else:
            raise DatabentoProviderError(
                "Databento canonical adapter currently supports quotes, trades, and bars"
            )
        return MarketDataBatch(query=query, records=tuple(records[-query.limit :]))

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        retrieved_at = self._now()
        if query.dataset_type is ProviderDatasetType.ACCOUNT_ENTITLEMENT:
            payload = self._metadata_list_datasets()
            observed_at = min(query.as_of, retrieved_at)
            availability_basis = AvailabilityBasis.RETRIEVAL_PROXY
            limitations = (
                "dataset discovery proves authenticated access, not legal usage approval",
                "exchange entitlements and paper-simulation rights remain separately governed",
            )
            source_identifier = "metadata.list_datasets"
        else:
            binding = self._resolve_dataset_binding(query.provider_symbol)
            schema = self._schema_for_dataset_type(query.dataset_type)
            payload = self._timeseries(
                binding=binding,
                schema=schema,
                start=query.start_at or self._dataset_default_start(query, schema),
                end=query.end_at or query.as_of,
                limit=query.limit,
            )
            observed_at = self._maximum_record_timestamp(payload, fallback=query.as_of)
            if observed_at > query.as_of:
                observed_at = query.as_of
            availability_basis = AvailabilityBasis.PROVIDER_TIMESTAMP
            limitations = self._dataset_limitations(query.dataset_type)
            source_identifier = f"{binding.dataset}:{schema}:{binding.provider_symbol}"
        return ProviderDatasetSnapshot(
            query=query,
            provider=self.name,
            source_version=DATABENTO_SOURCE_VERSION,
            observed_at=observed_at,
            available_at=observed_at,
            retrieved_at=retrieved_at,
            quality_state=DataQualityState.LIVE,
            availability_basis=availability_basis,
            payload=payload,
            provider_record_id=(
                "databento:"
                + hashlib.sha256(
                    f"{source_identifier}:{query.as_of.isoformat()}".encode("utf-8")
                ).hexdigest()
            ),
            limitations=limitations,
        )

    def capability_report(self) -> dict[str, Any]:
        """Return credential-safe datasets and schemas for configured bindings."""

        datasets = self._metadata_list_datasets()
        available = {str(item).strip() for item in datasets if str(item).strip()}
        binding_reports: list[dict[str, Any]] = []
        for binding in self.bindings.bindings:
            schemas: list[str] = []
            state = "blocked"
            blockers: list[str] = []
            if binding.dataset not in available:
                blockers.append("dataset_not_entitled_or_unavailable")
            else:
                schemas = self._metadata_list_schemas(binding.dataset)
                state = "available"
            binding_reports.append(
                {
                    "instrument_id": binding.instrument_id,
                    "dataset": binding.dataset,
                    "provider_symbol": binding.provider_symbol,
                    "venue": binding.venue,
                    "currency": binding.currency,
                    "stype_in": binding.stype_in,
                    "state": state,
                    "schemas": schemas,
                    "blockers": blockers,
                }
            )
        return {
            "schema_version": "databento-capability-report.v1",
            "provider": self.name,
            "configured": self.configured,
            "dataset_count": len(available),
            "datasets": sorted(available),
            "bindings": binding_reports,
            "licensing_approved": False,
            "paper_execution_authority": False,
            "real_money_authorized": False,
            "secret_values_disclosed": False,
        }

    def _resolve_dataset_binding(self, provider_symbol: str) -> DatabentoInstrumentBinding:
        normalized = provider_symbol.strip().upper()
        matches = tuple(
            item
            for item in self.bindings.bindings
            if item.provider_symbol == normalized or item.instrument_id.upper() == normalized
        )
        if len(matches) != 1:
            raise DatabentoProviderError(
                "raw Databento dataset queries require one configured provider symbol"
            )
        return matches[0]

    @staticmethod
    def _schema_for_market_query(query: MarketDataQuery) -> str:
        if query.data_type is MarketDataType.QUOTE:
            return "mbp-1"
        if query.data_type is MarketDataType.TRADE:
            return "trades"
        if query.data_type is MarketDataType.BAR:
            return {
                BarInterval.MINUTE: "ohlcv-1m",
                BarInterval.FIVE_MINUTES: "ohlcv-1m",
                BarInterval.HOUR: "ohlcv-1h",
                BarInterval.DAY: "ohlcv-1d",
            }[query.interval]
        raise DatabentoProviderError("unsupported canonical Databento query type")

    @staticmethod
    def _schema_for_dataset_type(dataset_type: ProviderDatasetType) -> str:
        mapping = {
            ProviderDatasetType.MARKET_PRICES: "ohlcv-1d",
            ProviderDatasetType.MARKET_HISTORY: "ohlcv-1d",
            ProviderDatasetType.QUOTES_LIQUIDITY: "mbp-1",
            ProviderDatasetType.DERIVATIVE_CONTRACTS: "definition",
            ProviderDatasetType.MARKET_CALENDARS: "status",
            ProviderDatasetType.BENCHMARKS: "ohlcv-1d",
            ProviderDatasetType.EXECUTION_INPUTS: "trades",
        }
        try:
            return mapping[dataset_type]
        except KeyError as error:
            raise DatabentoProviderError(
                f"unsupported Databento dataset type: {dataset_type.value}"
            ) from error

    @staticmethod
    def _dataset_limitations(dataset_type: ProviderDatasetType) -> tuple[str, ...]:
        base = (
            "provider timestamps and raw payload are preserved for downstream certification",
            "credential access does not establish exchange licensing or paper-simulation rights",
        )
        if dataset_type is ProviderDatasetType.DERIVATIVE_CONTRACTS:
            return base + (
                "contract definitions require lifecycle and margin reconciliation before allocation",
            )
        if dataset_type is ProviderDatasetType.QUOTES_LIQUIDITY:
            return base + (
                "venue-specific depth does not by itself establish consolidated executable liquidity",
            )
        return base

    def _timeseries(
        self,
        *,
        binding: DatabentoInstrumentBinding,
        schema: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise DatabentoProviderError(
                "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY is not configured"
            )
        if start >= end:
            raise DatabentoProviderError("Databento request start must precede end")
        data = {
            "dataset": binding.dataset,
            "symbols": binding.provider_symbol,
            "stype_in": binding.stype_in,
            "schema": schema,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "encoding": "json",
            "pretty_px": "true",
            "pretty_ts": "true",
            "map_symbols": "true",
            "limit": str(max(1, min(limit, 1_000_000))),
        }
        response = self._request(
            "POST",
            f"{DATABENTO_HISTORICAL_BASE}/timeseries.get_range",
            data=data,
            resource=f"timeseries {binding.dataset}/{schema}/{binding.provider_symbol}",
        )
        return self._json_lines(response)

    def _metadata_list_datasets(self) -> list[str]:
        response = self._request(
            "GET",
            f"{DATABENTO_HISTORICAL_BASE}/metadata.list_datasets",
            resource="dataset metadata",
        )
        payload = self._json_response(response, resource="dataset metadata")
        if not isinstance(payload, list):
            raise DatabentoProviderError("Databento dataset metadata must be a list")
        return [str(item).strip() for item in payload if str(item).strip()]

    def _metadata_list_schemas(self, dataset: str) -> list[str]:
        response = self._request(
            "GET",
            f"{DATABENTO_HISTORICAL_BASE}/metadata.list_schemas",
            params={"dataset": dataset},
            resource=f"schema metadata {dataset}",
        )
        payload = self._json_response(response, resource=f"schema metadata {dataset}")
        if not isinstance(payload, list):
            raise DatabentoProviderError("Databento schema metadata must be a list")
        return sorted(str(item).strip() for item in payload if str(item).strip())

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        data: Mapping[str, object] | None = None,
        resource: str,
    ) -> Any:
        if not self.api_key:
            raise DatabentoProviderError(
                "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY is not configured"
            )
        last_error: Exception | None = None
        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                request = self._http_post if method == "POST" else self._http_get
                kwargs: dict[str, Any] = {
                    "auth": (self.api_key, ""),
                    "timeout": self.timeout,
                }
                if params is not None:
                    kwargs["params"] = dict(params)
                if data is not None:
                    kwargs["data"] = dict(data)
                response = request(url, **kwargs)
                status_code = int(getattr(response, "status_code", 0))
                if status_code in self._policy.retry_statuses:
                    raise DatabentoProviderError(
                        f"temporary Databento HTTP {status_code} for {resource}"
                    )
                if status_code not in {200, 206}:
                    raise DatabentoProviderError(
                        f"Databento HTTP {status_code or 'unknown'} for {resource}"
                    )
                return response
            except (requests.RequestException, DatabentoProviderError) as error:
                last_error = error
                if attempt >= self._policy.max_attempts:
                    break
                self._sleeper(
                    float(self._policy.backoff_seconds) * (2 ** (attempt - 1))
                )
        raise DatabentoProviderError(
            f"unable to retrieve {resource} from Databento"
        ) from last_error

    @staticmethod
    def _json_response(response: Any, *, resource: str) -> Any:
        try:
            return response.json()
        except (TypeError, ValueError) as error:
            raise DatabentoProviderError(
                f"Databento returned invalid JSON for {resource}"
            ) from error

    @classmethod
    def _json_lines(cls, response: Any) -> list[dict[str, Any]]:
        if hasattr(response, "iter_lines"):
            raw_lines = response.iter_lines(decode_unicode=True)
        else:
            raw_lines = str(getattr(response, "text", "")).splitlines()
        records: list[dict[str, Any]] = []
        for raw in raw_lines:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            text = str(raw).strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as error:
                raise DatabentoProviderError(
                    "Databento JSON Lines response contains invalid JSON"
                ) from error
            if not isinstance(item, dict):
                raise DatabentoProviderError(
                    "Databento JSON Lines records must be objects"
                )
            records.append(item)
        return records

    def _normalize_quotes(
        self,
        payload: list[dict[str, Any]],
        query: MarketDataQuery,
        binding: DatabentoInstrumentBinding,
        retrieved_at: datetime,
    ) -> list[MarketQuote]:
        records: list[MarketQuote] = []
        for item in payload:
            observed_at = self._record_timestamp(item)
            if not self._within_query(observed_at, query):
                continue
            levels = item.get("levels")
            level = levels[0] if isinstance(levels, list) and levels else item
            if not isinstance(level, Mapping):
                continue
            try:
                bid = self._float(level.get("bid_px"), field_name="bid_px")
                ask = self._float(level.get("ask_px"), field_name="ask_px")
                bid_size = self._optional_float(level.get("bid_sz"))
                ask_size = self._optional_float(level.get("ask_sz"))
            except (TypeError, ValueError) as error:
                raise DatabentoProviderError("invalid Databento mbp-1 quote") from error
            records.append(
                MarketQuote(
                    instrument_id=binding.instrument_id,
                    currency=binding.currency,
                    bid=bid,
                    ask=ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    provenance=self._provenance(
                        item, binding, observed_at, retrieved_at, schema="mbp-1"
                    ),
                )
            )
        return records

    def _normalize_trades(
        self,
        payload: list[dict[str, Any]],
        query: MarketDataQuery,
        binding: DatabentoInstrumentBinding,
        retrieved_at: datetime,
    ) -> list[MarketTrade]:
        records: list[MarketTrade] = []
        for item in payload:
            observed_at = self._record_timestamp(item)
            if not self._within_query(observed_at, query):
                continue
            side_text = str(item.get("side") or "").strip().upper()
            side = {
                "B": TradeSide.BUY,
                "BUY": TradeSide.BUY,
                "A": TradeSide.SELL,
                "S": TradeSide.SELL,
                "SELL": TradeSide.SELL,
            }.get(side_text, TradeSide.UNKNOWN)
            try:
                price = self._float(item.get("price"), field_name="price")
                size = self._float(item.get("size"), field_name="size")
            except (TypeError, ValueError) as error:
                raise DatabentoProviderError("invalid Databento trade") from error
            records.append(
                MarketTrade(
                    instrument_id=binding.instrument_id,
                    currency=binding.currency,
                    price=price,
                    size=size,
                    side=side,
                    provenance=self._provenance(
                        item, binding, observed_at, retrieved_at, schema="trades"
                    ),
                )
            )
        return records

    def _normalize_bars(
        self,
        payload: list[dict[str, Any]],
        query: MarketDataQuery,
        binding: DatabentoInstrumentBinding,
        retrieved_at: datetime,
    ) -> list[PriceBar]:
        source_interval = (
            BarInterval.MINUTE
            if query.interval is BarInterval.FIVE_MINUTES
            else query.interval
        )
        duration = self._interval_duration(source_interval)
        records: list[PriceBar] = []
        for item in payload:
            start_at = self._record_timestamp(item)
            end_at = start_at + duration
            if not self._within_query(end_at, query):
                continue
            try:
                records.append(
                    PriceBar(
                        instrument_id=binding.instrument_id,
                        currency=binding.currency,
                        interval=source_interval,
                        start_at=start_at,
                        end_at=end_at,
                        open=self._float(item.get("open"), field_name="open"),
                        high=self._float(item.get("high"), field_name="high"),
                        low=self._float(item.get("low"), field_name="low"),
                        close=self._float(item.get("close"), field_name="close"),
                        volume=self._float(
                            item.get("volume") or 0.0, field_name="volume"
                        ),
                        provenance=self._provenance(
                            item,
                            binding,
                            end_at,
                            retrieved_at,
                            schema=f"ohlcv-{source_interval.value}",
                        ),
                    )
                )
            except (TypeError, ValueError) as error:
                raise DatabentoProviderError("invalid Databento OHLCV record") from error
        records.sort(key=lambda item: item.start_at)
        return records

    def _aggregate_five_minute_bars(
        self, records: list[PriceBar], query: MarketDataQuery
    ) -> list[PriceBar]:
        grouped: dict[datetime, list[PriceBar]] = {}
        for record in records:
            bucket = record.start_at.replace(
                minute=(record.start_at.minute // 5) * 5,
                second=0,
                microsecond=0,
            )
            grouped.setdefault(bucket, []).append(record)
        aggregates: list[PriceBar] = []
        for bucket, members in sorted(grouped.items()):
            members.sort(key=lambda item: item.start_at)
            expected = [bucket + timedelta(minutes=index) for index in range(5)]
            if [item.start_at for item in members] != expected:
                continue
            end_at = bucket + timedelta(minutes=5)
            if not self._within_query(end_at, query):
                continue
            last = members[-1]
            aggregates.append(
                PriceBar(
                    instrument_id=last.instrument_id,
                    currency=last.currency,
                    interval=BarInterval.FIVE_MINUTES,
                    start_at=bucket,
                    end_at=end_at,
                    open=members[0].open,
                    high=max(item.high for item in members),
                    low=min(item.low for item in members),
                    close=last.close,
                    volume=sum(item.volume for item in members),
                    provenance=MarketDataProvenance(
                        provider=self.name,
                        venue=last.provenance.venue,
                        observed_at=end_at,
                        retrieved_at=last.provenance.retrieved_at,
                        quality_state=DataQualityState.LIVE,
                        provider_record_id=(
                            f"databento:ohlcv-5m:{last.instrument_id}:"
                            f"{bucket.isoformat()}"
                        ),
                    ),
                )
            )
        return aggregates

    def _provenance(
        self,
        item: Mapping[str, Any],
        binding: DatabentoInstrumentBinding,
        observed_at: datetime,
        retrieved_at: datetime,
        *,
        schema: str,
    ) -> MarketDataProvenance:
        header = item.get("hd") if isinstance(item.get("hd"), Mapping) else {}
        instrument_id = header.get("instrument_id") or item.get("instrument_id")
        sequence = item.get("sequence") or header.get("ts_recv") or header.get("ts_event")
        return MarketDataProvenance(
            provider=self.name,
            venue=binding.venue,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            quality_state=DataQualityState.LIVE,
            provider_record_id=(
                f"databento:{binding.dataset}:{schema}:{instrument_id or binding.provider_symbol}:"
                f"{sequence or observed_at.isoformat()}"
            ),
        )

    @staticmethod
    def _record_timestamp(item: Mapping[str, Any]) -> datetime:
        header = item.get("hd") if isinstance(item.get("hd"), Mapping) else {}
        for value in (
            header.get("ts_recv"),
            header.get("ts_event"),
            item.get("ts_recv"),
            item.get("ts_event"),
            item.get("ts_record"),
        ):
            parsed = DatabentoProvider._timestamp(value)
            if parsed is not None:
                return parsed
        raise DatabentoProviderError("Databento record is missing a usable timestamp")

    @classmethod
    def _maximum_record_timestamp(
        cls, payload: list[dict[str, Any]], *, fallback: datetime
    ) -> datetime:
        values: list[datetime] = []
        for item in payload:
            try:
                values.append(cls._record_timestamp(item))
            except DatabentoProviderError:
                continue
        return max(values) if values else fallback

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = datetime.fromtimestamp(float(value) / 1_000_000_000, tz=timezone.utc)
        elif isinstance(value, str) and value.strip():
            text = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                try:
                    parsed = datetime.fromtimestamp(int(text) / 1_000_000_000, tz=timezone.utc)
                except (TypeError, ValueError, OverflowError):
                    return None
        else:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _within_query(observed_at: datetime, query: MarketDataQuery) -> bool:
        if observed_at > query.as_of:
            return False
        if query.start_at is not None and observed_at < query.start_at:
            return False
        return True

    @staticmethod
    def _float(value: object, *, field_name: str) -> float:
        if isinstance(value, bool) or value is None:
            raise TypeError(f"{field_name} must be numeric")
        result = float(value)
        if result != result or result in {float("inf"), float("-inf")}:
            raise ValueError(f"{field_name} must be finite")
        return result

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        return DatabentoProvider._float(value, field_name="optional numeric field")

    @staticmethod
    def _interval_duration(interval: BarInterval | None) -> timedelta:
        if interval is BarInterval.MINUTE:
            return timedelta(minutes=1)
        if interval is BarInterval.FIVE_MINUTES:
            return timedelta(minutes=5)
        if interval is BarInterval.HOUR:
            return timedelta(hours=1)
        if interval is BarInterval.DAY:
            return timedelta(days=1)
        raise DatabentoProviderError("unsupported Databento bar interval")

    @classmethod
    def _query_start(cls, query: MarketDataQuery) -> datetime:
        if query.start_at is not None:
            return query.start_at
        if query.data_type is MarketDataType.BAR:
            return query.as_of - {
                BarInterval.MINUTE: timedelta(hours=2),
                BarInterval.FIVE_MINUTES: timedelta(hours=8),
                BarInterval.HOUR: timedelta(days=3),
                BarInterval.DAY: timedelta(days=45),
            }[query.interval]
        return query.as_of - timedelta(minutes=15)

    @staticmethod
    def _dataset_default_start(query: ProviderDatasetQuery, schema: str) -> datetime:
        if schema in {"ohlcv-1d", "definition", "status"}:
            return query.as_of - timedelta(days=30)
        return query.as_of - timedelta(hours=1)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def load_databento_bindings(path: str | Path) -> DatabentoBindingRegistry:
    """Load a secret-free canonical-to-Databento binding registry."""

    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatabentoProviderError(
            f"cannot load Databento binding file {str(source)!r}"
        ) from error
    if not isinstance(payload, dict):
        raise DatabentoProviderError("Databento binding file must be a JSON object")
    if payload.get("schema_version") != "databento-instrument-bindings.v1":
        raise DatabentoProviderError("unsupported Databento binding schema")
    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, list):
        raise DatabentoProviderError("bindings must be a JSON array")
    bindings = tuple(
        DatabentoInstrumentBinding(
            instrument_id=str(item["instrument_id"]),
            dataset=str(item["dataset"]),
            provider_symbol=str(item["provider_symbol"]),
            venue=str(item["venue"]),
            currency=str(item["currency"]),
            stype_in=str(item.get("stype_in") or "raw_symbol"),
        )
        for item in raw_bindings
        if isinstance(item, dict)
    )
    if len(bindings) != len(raw_bindings):
        raise DatabentoProviderError("every binding entry must be a JSON object")
    return DatabentoBindingRegistry(bindings)


def build_databento_provider() -> DatabentoProvider:
    """Deployment factory for scheduled retrieval and diagnostics."""

    binding_path = os.getenv(
        "CAPITAL_INTELLIGENCE_DATABENTO_INSTRUMENT_BINDINGS",
        "config/databento_instrument_bindings.all_markets.json",
    )
    registry = load_databento_bindings(binding_path)
    return DatabentoProvider(bindings=registry)


__all__ = [
    "DATABENTO_HISTORICAL_BASE",
    "DATABENTO_SOURCE_VERSION",
    "DatabentoBindingRegistry",
    "DatabentoInstrumentBinding",
    "DatabentoProvider",
    "DatabentoProviderError",
    "DatabentoRetrievalPolicy",
    "build_databento_provider",
    "load_databento_bindings",
]
