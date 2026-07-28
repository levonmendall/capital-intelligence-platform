"""Provider-neutral raw dataset snapshots for licensed external feeds.

The canonical investment process should not leak a vendor's response schema into
its decision contracts.  This module therefore stores immutable raw snapshots
with explicit availability, retrieval, source-version, and integrity metadata.
Downstream normalization remains a separate governed step.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from data.observation import AvailabilityBasis, DataQualityState


class ProviderDatasetError(RuntimeError):
    """Raised when a provider dataset cannot be retrieved or validated."""


class ProviderDatasetType(str, Enum):
    """Raw provider datasets accepted by the governed landing zone."""

    ACCOUNT_ENTITLEMENT = "account_entitlement"
    EXCHANGE_DIRECTORY = "exchange_directory"
    SYMBOL_DIRECTORY = "symbol_directory"
    SECURITY_MASTER = "security_master"
    MARKET_PRICES = "market_prices"
    MARKET_HISTORY = "market_history"
    QUOTES_LIQUIDITY = "quotes_liquidity"
    CORPORATE_ACTIONS = "corporate_actions"
    FUNDAMENTALS = "fundamentals"
    FILINGS = "filings"
    MACRO = "macro"
    FX_RATES = "fx_rates"
    FIXED_INCOME = "fixed_income"
    FIXED_INCOME_TERMS = "fixed_income_terms"
    COMMODITY = "commodity"
    COMMODITY_CURVES = "commodity_curves"
    CRYPTO_MARKET_STRUCTURE = "crypto_market_structure"
    DERIVATIVE_CONTRACTS = "derivative_contracts"
    MARGIN_COLLATERAL = "margin_collateral"
    VOLATILITY_SURFACES = "volatility_surfaces"
    MARKET_CALENDARS = "market_calendars"
    BENCHMARKS = "benchmarks"
    EXECUTION_INPUTS = "execution_inputs"
    CANDIDATE_SCREENING = "candidate_screening"
    DECISION_INFORMATION = "decision_information"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _json_payload(value: object) -> dict[str, Any] | list[Any]:
    if not isinstance(value, (dict, list)):
        raise TypeError("payload must be a JSON object or array")
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("payload must contain finite JSON values") from error
    decoded = json.loads(encoded)
    if not isinstance(decoded, (dict, list)):
        raise ValueError("payload must encode an object or array")
    return decoded


@dataclass(frozen=True, slots=True)
class ProviderDatasetQuery:
    """One bounded request for a provider-native dataset."""

    dataset_type: ProviderDatasetType
    provider_symbol: str
    as_of: datetime
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = 10_000

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_type, ProviderDatasetType):
            raise TypeError("dataset_type must be ProviderDatasetType")
        object.__setattr__(
            self,
            "provider_symbol",
            _text(self.provider_symbol, field_name="provider_symbol").upper(),
        )
        as_of = _aware(self.as_of, field_name="as_of")
        object.__setattr__(self, "as_of", as_of)
        start_at = None
        if self.start_at is not None:
            start_at = _aware(self.start_at, field_name="start_at")
            if start_at > as_of:
                raise ValueError("start_at cannot follow as_of")
            object.__setattr__(self, "start_at", start_at)
        if self.end_at is not None:
            end_at = _aware(self.end_at, field_name="end_at")
            if end_at > as_of:
                raise ValueError("end_at cannot follow as_of")
            if start_at is not None and end_at < start_at:
                raise ValueError("end_at cannot precede start_at")
            object.__setattr__(self, "end_at", end_at)
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= self.limit <= 1_000_000:
            raise ValueError("limit must be between 1 and 1000000")


@dataclass(frozen=True, slots=True)
class ProviderDatasetSnapshot:
    """Immutable raw provider payload with point-in-time lineage."""

    query: ProviderDatasetQuery
    provider: str
    source_version: str
    observed_at: datetime
    available_at: datetime
    retrieved_at: datetime
    quality_state: DataQualityState
    availability_basis: AvailabilityBasis
    payload: dict[str, Any] | list[Any]
    provider_record_id: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        for field_name in ("provider", "source_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        observed_at = _aware(self.observed_at, field_name="observed_at")
        available_at = _aware(self.available_at, field_name="available_at")
        retrieved_at = _aware(self.retrieved_at, field_name="retrieved_at")
        if observed_at > available_at:
            raise ValueError("observed_at cannot follow available_at")
        if available_at > retrieved_at:
            raise ValueError("available_at cannot follow retrieved_at")
        if available_at > self.query.as_of:
            raise ValueError("snapshot was not available at query as_of")
        if not isinstance(self.quality_state, DataQualityState):
            raise TypeError("quality_state must be DataQualityState")
        if not isinstance(self.availability_basis, AvailabilityBasis):
            raise TypeError("availability_basis must be AvailabilityBasis")
        object.__setattr__(self, "payload", _json_payload(self.payload))
        if self.provider_record_id is not None:
            object.__setattr__(
                self,
                "provider_record_id",
                _text(
                    self.provider_record_id,
                    field_name="provider_record_id",
                ),
            )
        if not isinstance(self.limitations, tuple):
            raise TypeError("limitations must be a tuple")
        object.__setattr__(
            self,
            "limitations",
            tuple(_text(item, field_name="limitation") for item in self.limitations),
        )

    @property
    def content_hash(self) -> str:
        """Return a deterministic integrity fingerprint for the raw payload."""

        encoded = json.dumps(
            self.payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "provider-dataset-snapshot.v1",
            "dataset_type": self.query.dataset_type.value,
            "provider_symbol": self.query.provider_symbol,
            "query_as_of": self.query.as_of.isoformat(),
            "query_start_at": (
                None
                if self.query.start_at is None
                else self.query.start_at.isoformat()
            ),
            "query_end_at": (
                None
                if self.query.end_at is None
                else self.query.end_at.isoformat()
            ),
            "provider": self.provider,
            "source_version": self.source_version,
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "quality_state": self.quality_state.value,
            "availability_basis": self.availability_basis.value,
            "provider_record_id": self.provider_record_id,
            "limitations": list(self.limitations),
            "content_hash": self.content_hash,
            "payload": self.payload,
        }


@runtime_checkable
class ProviderDatasetProvider(Protocol):
    """Provider capable of returning governed raw dataset snapshots."""

    @property
    def name(self) -> str:
        ...

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        ...


__all__ = [
    "ProviderDatasetError",
    "ProviderDatasetProvider",
    "ProviderDatasetQuery",
    "ProviderDatasetSnapshot",
    "ProviderDatasetType",
]
