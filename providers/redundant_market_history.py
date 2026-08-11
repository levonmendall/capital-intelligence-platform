"""Governed point-in-time market-history redundancy for investable assets.

Failover is scoped to provider + capability + dataset, so an OPRA entitlement failure
cannot disable the same vendor's futures, stock, FX, or crypto capability. Candidates
must represent the exact same economic instrument. Fixed-income candidates additionally
require explicit exact-security identity; aggregate TRACE, benchmark yields, auction
prices, and proxy securities can never satisfy individual-bond price evidence.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite

from providers.redundancy_audit import (
    ProviderCapabilityKey,
    RedundancyAuditLedger,
    current_redundancy_ledger,
)


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
    pass


@dataclass(frozen=True, slots=True)
class MarketHistoryCandidate:
    provider: str
    capability: str
    dataset: str
    provider_symbol: str
    instrument_identity: str
    loader: Callable[[], Sequence[Mapping[str, object]]]
    configured: bool = True
    # ``authenticated`` is prior proof only. False means authentication has not yet
    # been proven for this capability in the current cycle; it is not a reason to skip
    # an otherwise configured candidate. A successful request promotes the audit state.
    authenticated: bool = False
    certified_for_evidence_role: bool = True
    fixed_income: bool = False
    exact_security_identity: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "capability",
            "dataset",
            "provider_symbol",
            "instrument_identity",
        ):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(
                self,
                field_name,
                value.lower()
                if field_name in {"provider", "capability"}
                else value,
            )
        if not callable(self.loader):
            raise TypeError("loader must be callable")
        if self.fixed_income and not self.exact_security_identity:
            raise ValueError(
                "fixed-income market-history candidates require exact-security identity"
            )

    @property
    def key(self) -> ProviderCapabilityKey:
        return ProviderCapabilityKey(self.provider, self.capability, self.dataset)


@dataclass(frozen=True, slots=True)
class RoutedMarketHistory:
    provider: str
    capability: str
    dataset: str
    provider_symbol: str
    instrument_identity: str
    rows: tuple[dict[str, object], ...]
    evidence_identifiers: tuple[str, ...]
    attempted_capabilities: tuple[str, ...]
    failed_capabilities: tuple[tuple[str, str], ...]
    failed_over: bool


ALL_ASSET_REDUNDANCY_POLICY: dict[str, dict[str, tuple[str, ...]]] = {
    "us_equity": {
        "history": (
            "alpaca",
            "tradier",
            "massive",
            "twelve_data",
            "yahoo",
            "eodhd",
        ),
        "quote": (
            "alpaca",
            "tradier",
            "massive",
            "twelve_data",
            "alpha_vantage",
            "yahoo",
        ),
    },
    "us_etf": {
        "history": (
            "alpaca",
            "tradier",
            "massive",
            "twelve_data",
            "yahoo",
            "eodhd",
        ),
        "quote": (
            "alpaca",
            "tradier",
            "massive",
            "twelve_data",
            "alpha_vantage",
            "yahoo",
        ),
    },
    "international_equity": {
        "reference": ("eodhd", "twelve_data", "openfigi"),
        "history": ("eodhd", "twelve_data", "yahoo"),
    },
    "fx": {
        "reference": ("eodhd", "twelve_data"),
        "history": ("twelve_data", "massive", "eodhd", "yahoo"),
    },
    "crypto": {
        "history": ("coinbase", "kraken", "massive", "twelve_data", "yahoo"),
        "quote_validation": ("coinbase", "kraken"),
    },
    "future": {
        "reference": ("databento", "massive"),
        "history": ("databento", "massive", "yahoo"),
    },
    "fixed_income": {
        "reference": ("treasury_fiscal_data", "eodhd", "openfigi"),
        "market_context": ("finra", "treasury_fiscal_data", "fred"),
        "history": ("ice_evaluated_fixed_income", "eodhd"),
    },
    "option": {
        "reference": ("databento", "massive"),
        "history": ("databento", "massive"),
        "active_chain_corroboration": ("tradier",),
    },
}


def _status_from_error(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    match = re.search(r"\bHTTP\s+(\d{3})\b", str(error), re.IGNORECASE)
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
    if any(
        marker in text
        for marker in (
            "invalid symbol",
            "symbol mismatch",
            "unsupported",
            "request contract",
            "identity mismatch",
        )
    ):
        return ProviderFailureClass.REQUEST_CONTRACT
    return ProviderFailureClass.PROVIDER_EVIDENCE_UNAVAILABLE


def _aware(value: object) -> datetime | None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        return None
    return value.astimezone(timezone.utc)


def _normalize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    as_of: datetime,
) -> tuple[dict[str, object], ...]:
    by_timestamp: dict[datetime, dict[str, object]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        observed = _aware(raw.get("t"))
        if observed is None or observed > as_of:
            continue
        try:
            close = float(raw.get("c"))  # type: ignore[arg-type]
            volume = max(0.0, float(raw.get("v", 0.0)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not isfinite(close) or close <= 0.0 or not isfinite(volume):
            continue
        by_timestamp[observed] = {"t": observed, "c": close, "v": volume}
    return tuple(by_timestamp[key] for key in sorted(by_timestamp))


class RedundantMarketHistoryRouter:
    def __init__(self, *, audit: RedundancyAuditLedger | None = None) -> None:
        self._blocked: dict[ProviderCapabilityKey, ProviderFailureClass] = {}
        self.audit = audit

    @property
    def blocked_capabilities(
        self,
    ) -> Mapping[ProviderCapabilityKey, ProviderFailureClass]:
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
        if (
            isinstance(minimum_rows, bool)
            or not isinstance(minimum_rows, int)
            or minimum_rows < 1
        ):
            raise ValueError("minimum_rows must be a positive integer")
        if not candidates:
            raise RedundantMarketHistoryError(
                "no certified market-history candidates were supplied"
            )
        identities = {item.instrument_identity for item in candidates}
        if len(identities) != 1:
            raise RedundantMarketHistoryError(
                "provider failover cannot cross economic-instrument identities"
            )
        if any(
            item.fixed_income and not item.exact_security_identity
            for item in candidates
        ):
            raise RedundantMarketHistoryError(
                "fixed-income failover requires exact-security identity"
            )

        ledger = self.audit or current_redundancy_ledger()
        attempted: list[str] = []
        failures: list[tuple[str, str]] = []
        for index, candidate in enumerate(candidates):
            key = candidate.key
            if ledger is not None:
                ledger.declare(
                    key,
                    configured=candidate.configured,
                    authenticated=candidate.authenticated,
                    routed=True,
                    certified_for_evidence_role=candidate.certified_for_evidence_role,
                )
            if not candidate.configured:
                failures.append((key.identifier, "not_configured"))
                continue
            if not candidate.certified_for_evidence_role:
                failures.append((key.identifier, "not_certified_for_evidence_role"))
                continue
            blocked = self._blocked.get(key)
            if blocked is not None:
                failures.append(
                    (key.identifier, f"cycle_blocked:{blocked.value}")
                )
                continue
            attempted.append(key.identifier)
            if ledger is not None:
                ledger.attempted(key)
            try:
                raw_rows = candidate.loader()
                rows = _normalize_rows(
                    raw_rows,
                    as_of=as_of.astimezone(timezone.utc),
                )
            except Exception as error:
                failure_class = classify_provider_failure(error)
                failures.append((key.identifier, failure_class.value))
                if ledger is not None:
                    ledger.failed(key, failure_class.value)
                if failure_class in _PERMANENT_FOR_CYCLE:
                    self._blocked[key] = failure_class
                continue
            if len(rows) < minimum_rows:
                failure = ProviderFailureClass.INSUFFICIENT_EVIDENCE
                failures.append((key.identifier, failure.value))
                if ledger is not None:
                    ledger.failed(key, failure.value)
                continue
            first = rows[0]["t"]
            last = rows[-1]["t"]
            source = (
                f"market-history:{key.identifier}:{candidate.provider_symbol}:"
                f"{first.isoformat()}:{last.isoformat()}:rows={len(rows)}"
            )
            failed_over = index > 0 or bool(failures)
            if ledger is not None:
                ledger.used(
                    key,
                    source_identifiers=(source,),
                    failed_over=failed_over,
                )
            return RoutedMarketHistory(
                provider=candidate.provider,
                capability=candidate.capability,
                dataset=candidate.dataset,
                provider_symbol=candidate.provider_symbol,
                instrument_identity=candidate.instrument_identity,
                rows=rows,
                evidence_identifiers=(source,),
                attempted_capabilities=tuple(attempted),
                failed_capabilities=tuple(failures),
                failed_over=failed_over,
            )
        detail = (
            ",".join(
                f"{provider}={reason}" for provider, reason in failures
            )
            or "no_candidates"
        )
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
