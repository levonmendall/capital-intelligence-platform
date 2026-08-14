"""Bounded compatibility fallback for Massive futures reference discovery.

The canonical Massive reference adapter remains the strict point-in-time path. This
runtime wrapper is used only when Massive accepts that exact-date request (HTTP 200) but
returns no records for every configured root during a near-current diagnostic. In that
specific case it retries each configured product root without the provider-side ``date``
filter, keeps ``active=true``, and independently enforces the original as-of date against
first/last trade dates before accepting a contract.

Historical requests, provider/auth failures, malformed responses, pagination failures,
and incomplete configured-root coverage remain fail-closed. The wrapper has no
investment, construction, execution, or real-money authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from providers.massive_futures_reference import (
    MassiveFuturesReferenceProvider as _StrictMassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import (
    MASSIVE_BASE_URL,
    MassiveFuturesContract,
    MassiveMultiAssetError,
)


_FUTURES_CONTRACT_PATH = "/futures/v1/contracts"
_CURRENT_REFERENCE_LOOKBACK = timedelta(hours=36)
_CURRENT_REFERENCE_FUTURE_TOLERANCE = timedelta(hours=6)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MassiveFuturesReferenceProvider(_StrictMassiveFuturesReferenceProvider):
    """Strict reference provider with a bounded near-current empty-response fallback."""

    def __init__(
        self,
        *args: object,
        reference_clock: Callable[[], datetime] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._reference_clock = reference_clock or _utc_now

    def _current_fallback_allowed(self, as_of: datetime) -> bool:
        now = self._reference_clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("reference_clock must return a timezone-aware datetime")
        normalized_now = now.astimezone(timezone.utc)
        normalized_as_of = as_of.astimezone(timezone.utc)
        return (
            normalized_now - _CURRENT_REFERENCE_LOOKBACK
            <= normalized_as_of
            <= normalized_now + _CURRENT_REFERENCE_FUTURE_TOLERANCE
        )

    @staticmethod
    def _strict_empty_for_all_requested_roots(
        rows: Sequence[Mapping[str, object]],
        roots: Sequence[str],
    ) -> bool:
        requested = {str(root).strip().upper() for root in roots if str(root).strip()}
        if not requested:
            return False
        indexed = {
            str(row.get("root") or "").strip().upper(): row
            for row in rows
            if str(row.get("root") or "").strip()
        }
        if not requested.issubset(indexed):
            return False
        return all(
            indexed[root].get("http_status") == 200
            and int(indexed[root].get("raw_result_count", 0)) == 0
            and str(indexed[root].get("failure_reason") or "")
            == "empty_provider_response"
            for root in requested
        )

    def _fallback_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str],
        maximum_pages: int,
        strict_rows: Sequence[Mapping[str, object]],
    ) -> tuple[MassiveFuturesContract, ...]:
        target_codes = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        if not target_codes:
            raise MassiveMultiAssetError(
                "Massive current-reference fallback requires configured product roots"
            )

        strict_by_root = {
            str(row.get("root") or "").strip().upper(): row for row in strict_rows
        }
        reference_date = as_of.astimezone(timezone.utc).date()
        reference_date_text = reference_date.isoformat()
        result: dict[str, MassiveFuturesContract] = {}
        request_count = 0
        self._reference_telemetry = {}

        for target_code in target_codes:
            strict_row = strict_by_root.get(target_code, {})
            root_telemetry: dict[str, object] = {
                "root": target_code,
                "request_path": _FUTURES_CONTRACT_PATH,
                "request_params": {
                    "active": "true",
                    "limit": 1000,
                    "product_code": target_code,
                },
                "query_mode": "current_active_without_date",
                "fallback_used": True,
                "strict_http_status": strict_row.get("http_status"),
                "strict_raw_result_count": int(
                    strict_row.get("raw_result_count", 0)
                ),
                "http_status": None,
                "request_attempts": 0,
                "retry_count": 0,
                "rate_limited": False,
                "pages": 0,
                "raw_result_count": 0,
                "parsed_contract_count": 0,
                "schema_invalid_count": 0,
                "root_matched_count": 0,
                "point_in_time_valid_count": 0,
                "usable_count": 0,
                "next_url_observed": False,
                "pagination_complete": False,
                "sample_contract": None,
                "failure_reason": "pending",
            }
            self._reference_telemetry[target_code] = root_telemetry

            url = f"{MASSIVE_BASE_URL}{_FUTURES_CONTRACT_PATH}"
            # Keep credentials outside the public/sanitized request_params telemetry.
            params: dict[str, object] = {
                "active": "true",
                "limit": 1000,
                "product_code": target_code,
                "apiKey": self.api_key,
            }

            try:
                for _ in range(maximum_pages):
                    if request_count and self.minimum_call_interval_seconds > 0.0:
                        self._sleeper(self.minimum_call_interval_seconds)
                    payload = self._reference_get(
                        url,
                        params=params,
                        root_telemetry=root_telemetry,
                    )
                    request_count += 1
                    root_telemetry["pages"] = int(root_telemetry["pages"]) + 1

                    raw = payload.get("results") if isinstance(payload, Mapping) else None
                    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                        root_telemetry["failure_reason"] = "response_schema_failure"
                        raise MassiveMultiAssetError(
                            "Massive futures current-reference fallback response is missing results"
                        )
                    root_telemetry["raw_result_count"] = int(
                        root_telemetry["raw_result_count"]
                    ) + len(raw)

                    for item in raw:
                        if not isinstance(item, Mapping):
                            root_telemetry["schema_invalid_count"] = int(
                                root_telemetry["schema_invalid_count"]
                            ) + 1
                            continue
                        ticker = str(item.get("ticker") or "").strip().upper()
                        product = str(item.get("product_code") or "").strip().upper()
                        venue = str(item.get("trading_venue") or "").strip().upper()
                        first = str(item.get("first_trade_date") or "").strip()
                        last = str(item.get("last_trade_date") or "").strip()
                        first_date = self._parse_date(first)
                        last_date = self._parse_date(last)
                        if (
                            not ticker
                            or not product
                            or not venue
                            or first_date is None
                            or last_date is None
                        ):
                            root_telemetry["schema_invalid_count"] = int(
                                root_telemetry["schema_invalid_count"]
                            ) + 1
                            continue

                        root_telemetry["parsed_contract_count"] = int(
                            root_telemetry["parsed_contract_count"]
                        ) + 1
                        if product != target_code:
                            continue
                        root_telemetry["root_matched_count"] = int(
                            root_telemetry["root_matched_count"]
                        ) + 1

                        if not (first_date <= reference_date <= last_date):
                            continue
                        root_telemetry["point_in_time_valid_count"] = int(
                            root_telemetry["point_in_time_valid_count"]
                        ) + 1

                        raw_active = item.get("active", True)
                        active = (
                            raw_active.strip().lower() == "true"
                            if isinstance(raw_active, str)
                            else bool(raw_active)
                        )
                        if not active:
                            continue

                        root_telemetry["usable_count"] = int(
                            root_telemetry["usable_count"]
                        ) + 1
                        if root_telemetry["sample_contract"] is None:
                            root_telemetry["sample_contract"] = self._sample_contract(
                                ticker=ticker,
                                product=product,
                                venue=venue,
                                first=first_date.isoformat(),
                                last=last_date.isoformat(),
                                active=active,
                            )
                        result[ticker] = MassiveFuturesContract(
                            ticker=ticker,
                            product_code=product,
                            trading_venue=venue,
                            first_trade_date=first_date.isoformat(),
                            last_trade_date=last_date.isoformat(),
                            settlement_date=(
                                str(item.get("settlement_date")).strip()
                                if item.get("settlement_date")
                                else None
                            ),
                            active=active,
                            source_identifier=(
                                f"massive:futures-contract:{ticker}:{reference_date_text}"
                            ),
                        )

                    next_url = str(payload.get("next_url") or "").strip()
                    if not next_url:
                        root_telemetry["pagination_complete"] = True
                        break
                    root_telemetry["next_url_observed"] = True
                    parsed = urlparse(next_url)
                    if parsed.scheme != "https" or parsed.netloc != "api.massive.com":
                        root_telemetry["failure_reason"] = "invalid_pagination_url"
                        raise MassiveMultiAssetError(
                            "Massive futures current-reference fallback returned an invalid next_url"
                        )
                    url = next_url
                    params = {"apiKey": self.api_key}

                self._finalize_root_telemetry(root_telemetry)
                if not bool(root_telemetry["pagination_complete"]):
                    raise MassiveMultiAssetError(
                        "Massive futures current-reference fallback pagination exceeded "
                        f"the completeness guard for {target_code}"
                    )
            except MassiveMultiAssetError as error:
                self._finalize_root_telemetry(root_telemetry)
                telemetry_detail = self._compact_failure_telemetry((root_telemetry,))
                raise MassiveMultiAssetError(
                    f"{error}; massive_futures_telemetry={telemetry_detail}",
                    status_code=error.status_code,
                    retryable=error.retryable,
                ) from error

        telemetry = self.reference_telemetry
        incomplete = tuple(
            row
            for row in telemetry
            if str(row.get("root") or "") in target_codes
            and int(row.get("usable_count", 0)) < 1
        )
        if incomplete:
            for row in incomplete:
                if (
                    row.get("http_status") == 200
                    and int(row.get("raw_result_count", 0)) == 0
                ):
                    self._reference_telemetry[str(row.get("root"))][
                        "failure_reason"
                    ] = "empty_current_fallback_response"
            telemetry_detail = self._compact_failure_telemetry(
                self.reference_telemetry
            )
            missing = ", ".join(
                str(row.get("root") or "unknown") for row in incomplete
            )
            raise MassiveMultiAssetError(
                "Massive current-reference futures fallback did not establish complete "
                f"configured-root coverage: {missing}; "
                f"massive_futures_telemetry={telemetry_detail}"
            )

        return tuple(result[key] for key in sorted(result))

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        try:
            return super().futures_contracts(
                as_of=as_of,
                product_codes=product_codes,
                maximum_pages=maximum_pages,
            )
        except MassiveMultiAssetError:
            strict_rows = self.reference_telemetry
            if not self._strict_empty_for_all_requested_roots(
                strict_rows, product_codes
            ):
                raise
            if not self._current_fallback_allowed(as_of):
                raise
            return self._fallback_contracts(
                as_of=as_of,
                product_codes=product_codes,
                maximum_pages=maximum_pages,
                strict_rows=strict_rows,
            )


__all__ = ["MassiveFuturesReferenceProvider"]
