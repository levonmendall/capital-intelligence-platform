"""Exact dated-futures historical evidence using Databento CME Globex data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.databento import (
    DatabentoBindingRegistry,
    DatabentoInstrumentBinding,
    DatabentoProvider,
    DatabentoProviderError,
)


class DatabentoFuturesHistoryProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._configured = DatabentoProvider(api_key=api_key).configured

    @property
    def configured(self) -> bool:
        return self._configured

    def daily_history(
        self,
        *,
        symbol: str,
        venue: str,
        currency: str,
        as_of: datetime,
        history_days: int,
        dataset: str = "GLBX.MDP3",
    ) -> tuple[dict[str, object], ...]:
        normalized = str(symbol).strip().upper()
        if not normalized:
            raise DatabentoProviderError("exact futures symbol cannot be empty")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        binding = DatabentoInstrumentBinding(
            instrument_id=f"future:{normalized}",
            dataset=dataset,
            provider_symbol=normalized,
            venue=str(venue).strip().upper() or "CME",
            currency=str(currency).strip().upper() or "USD",
            stype_in="raw_symbol",
        )
        provider = DatabentoProvider(
            api_key=self._api_key,
            bindings=DatabentoBindingRegistry((binding,)),
            timeout=15,
        )
        snapshot = provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.MARKET_HISTORY,
                provider_symbol=normalized,
                as_of=as_of,
                start_at=as_of - timedelta(days=history_days),
                end_at=as_of,
                limit=10_000,
            )
        )
        payload = snapshot.payload
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise DatabentoProviderError("Databento futures history payload is invalid")
        rows: list[dict[str, object]] = []
        cutoff = as_of.astimezone(timezone.utc)
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            observed = self._timestamp(item.get("ts_event") or item.get("ts_recv") or item.get("timestamp"))
            close = self._number(item.get("close"))
            volume = self._number(item.get("volume"), default=0.0)
            if observed is None or observed > cutoff or close <= 0.0:
                continue
            rows.append({"t": observed, "c": close, "v": max(0.0, volume)})
        rows.sort(key=lambda item: item["t"])  # type: ignore[arg-type]
        if not rows:
            raise DatabentoProviderError(
                f"Databento returned no exact dated-futures bars for {normalized}"
            )
        return tuple(rows)

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return None
            return value.astimezone(timezone.utc)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if numeric > 1e17:
                numeric /= 1e9
            elif numeric > 1e14:
                numeric /= 1e6
            elif numeric > 1e11:
                numeric /= 1e3
            try:
                return datetime.fromtimestamp(numeric, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _number(value: object, *, default: float = 0.0) -> float:
        if isinstance(value, bool) or value in (None, ""):
            return default
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default


__all__ = ["DatabentoFuturesHistoryProvider"]
