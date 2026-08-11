"""Governed provider redundancy for point-in-time market-history evidence.

This module centralizes provider failover semantics for investable assets. It does not
rank instruments, relax evidence requirements, authorize construction, or grant any
execution authority. Callers supply ordered provider candidates that must represent the
same economic instrument and evidence role. The first candidate that satisfies the
existing minimum-history contract wins; if all candidates fail, evidence remains
fail-closed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any


class ProviderFailureClass(str, Enum):
    AUTHENTICATION_OR_ENTITLEMENT = "authentication_or_entitlement"
    ACCESS_OR_CREDIT_CAP = "access_or_credit_cap"
    RATE_LIMIT = "rate_limit"
    PROVIDER_5XX = "provider_5xx"
    TRANSIENT_PROVIDER_FAILURE = "transient_provider_failure"
    REQUEST_CONTRACT = "request_contract"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PROVIDER_EVIDENCE_UNAVAILABLE = "provider_evidence_unavailable"


_PERMANENT_FOR_CYCLE = frozenset(
    {
        ProviderFailureClass.AUTHENTICATION_OR_ENTITLEMENT,
        ProviderFailureClass.ACCESS_OR_CREDIT_CAP,
        ProviderFailureClass.REQUEST_CONTRACT,
    }
)


class RedundantMarketHistoryError(RuntimeError):
    """Raised when no certified history candidate can satisfy the evidence contract."""


@dataclass(frozen=True, slots=True)
class MarketHistoryCandidate:
    provider: str
    provider_symbol: str
    loader: Callable[[], Sequence[Mapping[str, object]]]
    configured: bool = True

    def __post_init__(self) -> None:
        provider = str(self.provider).strip().lower()
        symbol = str(self.provider_symbol).strip()
        if not provider or not symbol:
            raise ValueError("provider and provider_symbol cannot be empty")
        if not callable(self.loader):
            raise TypeError("loader must be callable")
        if not isinstance(self.configured, bool):
            raise TypeError("configured must be a bool")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "provider_symbol", symbol)


@dataclass(frozen=True, slots=True)
class RoutedMarketHistory:
    provider: str
    provider_symbol: str
    rows: tuple[dict[str, object], ...]
    evidence_identifiers: tuple[str, ...]
    attempted_providers: tuple[str, ...]
    failed_providers: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("routed market history requires evidence rows")


# Capability policy is intentionally explicit. Each tuple contains independently
# sourced providers for the same evidence role. Quote-only crypto venues are kept out
# of the history role but are listed under quote_validation.
ALL_ASSET_REDUNDANCY_POLICY: dict[str, dict[str, tuple[str, ...]]] = {
    "us_equity": {
        "history": ("alpaca", "yahoo", "twelve_data"),
        "quote": ("alpaca", "yahoo", "twelve_data", "alpha_vantage"),
    },
    "us_etf": {
        "history": ("alpaca", "yahoo", "twelve_data"),
        "quote": ("alpaca", "yahoo", "twelve_data", "alpha_vantage"),
    },
    "international_equity": {
        "reference": ("eodhd", "twelve_data"),
        "history": ("yahoo", "twelve_data", "eodhd"),
    },
    "fx": {
        "reference": ("eodhd", "twelve_data"),
        "history": ("yahoo", "twelve_data", "eodhd"),
    },
    "crypto": {
        "history": ("yahoo", "twelve_data"),
        "quote_validation": ("coinbase", "kraken"),
    },
    "future": {
        "history": ("yahoo", "databento"),
    },
    "fixed_income": {
        "reference": ("eodhd", "twelve_data"),
        "history": ("eodhd", "twelve_data"),
    },
    "option": {
        "reference": ("databento", "massive"),
        "history": ("databento", "massive"),
    },
}


def _status_from_error(error: BaseException) -> int | None:
    value = getattr(error, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    match = re.search(r"\bHTTP\s+(\d{3})\b", str(error), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def classify_provider_failure(error: BaseException) -> ProviderFailureClass:
    status = _status_from_error(error)
    if status in {401, 403}:
        return ProviderFailureClass.AUTHENTICATION_OR_ENTITLEMENT
    if status == 402:
        return ProviderFailureClass.ACCESS_OR_CREDIT_CAP
    if status == 429:
        return ProviderFailureClass.RATE_LIMIT
    if isinstance(status, int) and 500 <= status <= 599:
        return ProviderFailureClass.PROVIDER_5XX
    if bool(getattr(error, "retryable", False)):
        return ProviderFailureClass.TRANSIENT_PROVIDER_FAILURE
    text = str(error).lower()
    if any(marker in text for marker in ("invalid symbol", "symbol mismatch", "unsupported", "request contract")):
        return ProviderFailureClass.REQUEST_CONTRACT
    return ProviderFailureClass.PROVIDER_EVIDENCE_UNAVAILABLE


def _aware(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _normalize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    as_of: datetime,
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        observed = _aware(raw.get("t"))
        if observed is None or observed > as_of:
            continue
        close_raw = raw.get("c")
        volume_raw = raw.get("v", 0.0)
        try:
            close = float(close_raw)  # type: ignore[arg-type]
            volume = max(0.0, float(volume_raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not isfinite(close) or close <= 0.0 or not isfinite(volume):
            continue
        normalized.append({"t": observed, "c": close, "v": volume})
    normalized.sort(key=lambda item: item["t"])  # type: ignore[arg-type]
    by_timestamp: dict[datetime, dict[str, object]] = {}
    for item in normalized:
        by_timestamp[item["t"]] = item  # type: ignore[index]
    return tuple(by_timestamp[key] for key in sorted(by_timestamp))


class RedundantMarketHistoryRouter:
    """Route history requests across equivalent providers with a cycle circuit breaker."""

    def __init__(self) -> None:
        self._blocked: dict[str, ProviderFailureClass] = {}

    @property
    def blocked_providers(self) -> Mapping[str, ProviderFailureClass]:
        return dict(self._blocked)

    def fetch(
        self,
        candidates: Sequence[MarketHistoryCandidate],
        *,
        as_of: datetime,
        minimum_rows: int,
    ) -> RoutedMarketHistory:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if isinstance(minimum_rows, bool) or not isinstance(minimum_rows, int) or minimum_rows < 1:
            raise ValueError("minimum_rows must be a positive integer")
        attempted: list[str] = []
        failures: list[tuple[str, str]] = []
        for candidate in candidates:
            if not candidate.configured:
                failures.append((candidate.provider, "not_configured"))
                continue
            blocked = self._blocked.get(candidate.provider)
            if blocked is not None:
                failures.append((candidate.provider, f"cycle_blocked:{blocked.value}"))
                continue
            attempted.append(candidate.provider)
            try:
                raw_rows = candidate.loader()
                rows = _normalize_rows(raw_rows, as_of=as_of.astimezone(timezone.utc))
            except Exception as error:  # provider adapters expose heterogeneous errors
                failure_class = classify_provider_failure(error)
                failures.append((candidate.provider, failure_class.value))
                if failure_class in _PERMANENT_FOR_CYCLE:
                    self._blocked[candidate.provider] = failure_class
                continue
            if len(rows) < minimum_rows:
                failures.append((candidate.provider, ProviderFailureClass.INSUFFICIENT_EVIDENCE.value))
                continue
            first = rows[0]["t"]
            last = rows[-1]["t"]
            source = (
                f"market-history:{candidate.provider}:{candidate.provider_symbol}:"
                f"{first.isoformat()}:{last.isoformat()}:rows={len(rows)}"
            )
            return RoutedMarketHistory(
                provider=candidate.provider,
                provider_symbol=candidate.provider_symbol,
                rows=rows,
                evidence_identifiers=(source,),
                attempted_providers=tuple(attempted),
                failed_providers=tuple(failures),
            )
        detail = ",".join(f"{provider}={reason}" for provider, reason in failures) or "no_candidates"
        raise RedundantMarketHistoryError(
            "certified market-history providers could not satisfy the existing evidence contract; "
            + detail
        )


__all__ = [
    "ALL_ASSET_REDUNDANCY_POLICY",
    "MarketHistoryCandidate",
    "ProviderFailureClass",
    "RedundantMarketHistoryError",
    "RedundantMarketHistoryRouter",
    "RoutedMarketHistory",
    "classify_provider_failure",
]
