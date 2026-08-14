"""Governed Massive futures-reference enumeration with credential-safe telemetry.

This adapter changes only reference-data acquisition. It preserves exact point-in-time
contract identity and complete configured-root coverage while preventing a broad futures
directory crawl from exhausting the provider call budget. It has no investment,
construction, execution, or real-money authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

from providers.massive_multi_asset import (
    MASSIVE_BASE_URL,
    MassiveFuturesContract,
    MassiveMultiAssetError,
    MassiveMultiAssetProvider,
)


_DEFAULT_MINIMUM_CALL_INTERVAL_SECONDS = 12.5
_DEFAULT_RATE_LIMIT_RETRY_SECONDS = 60.0
_DEFAULT_REFERENCE_MAX_ATTEMPTS = 4
_FUTURES_CONTRACT_PATH = "/futures/v1/contracts"


class MassiveFuturesReferenceProvider(MassiveMultiAssetProvider):
    """Retrieve exact dated contracts with root-scoped, rate-budgeted requests."""

    def __init__(
        self,
        *args: object,
        minimum_call_interval_seconds: float = _DEFAULT_MINIMUM_CALL_INTERVAL_SECONDS,
        rate_limit_retry_seconds: float = _DEFAULT_RATE_LIMIT_RETRY_SECONDS,
        reference_max_attempts: int = _DEFAULT_REFERENCE_MAX_ATTEMPTS,
        **kwargs: object,
    ) -> None:
        if isinstance(minimum_call_interval_seconds, bool) or not isinstance(
            minimum_call_interval_seconds, (int, float)
        ):
            raise TypeError("minimum_call_interval_seconds must be numeric")
        if not 0.0 <= float(minimum_call_interval_seconds) <= 60.0:
            raise ValueError("minimum_call_interval_seconds must be between 0 and 60")
        if isinstance(rate_limit_retry_seconds, bool) or not isinstance(
            rate_limit_retry_seconds, (int, float)
        ):
            raise TypeError("rate_limit_retry_seconds must be numeric")
        if not 0.0 <= float(rate_limit_retry_seconds) <= 120.0:
            raise ValueError("rate_limit_retry_seconds must be between 0 and 120")
        if isinstance(reference_max_attempts, bool) or not isinstance(
            reference_max_attempts, int
        ):
            raise TypeError("reference_max_attempts must be an integer")
        if not 1 <= reference_max_attempts <= 8:
            raise ValueError("reference_max_attempts must be between 1 and 8")

        # A reference request owns its retry schedule so an HTTP 429 does not receive
        # several short retries inside the same provider rate-limit window.
        kwargs = dict(kwargs)
        kwargs["max_attempts"] = 1
        super().__init__(*args, **kwargs)
        self.minimum_call_interval_seconds = float(minimum_call_interval_seconds)
        self.rate_limit_retry_seconds = float(rate_limit_retry_seconds)
        self.reference_max_attempts = reference_max_attempts
        self._reference_telemetry: dict[str, dict[str, object]] = {}

    @property
    def reference_telemetry(self) -> tuple[Mapping[str, object], ...]:
        """Return sanitized per-root telemetry from the most recent enumeration."""

        return tuple(
            dict(self._reference_telemetry[key])
            for key in sorted(self._reference_telemetry)
        )

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        last_error: MassiveMultiAssetError | None = None
        for attempt in range(1, self.reference_max_attempts + 1):
            root_telemetry["request_attempts"] = int(
                root_telemetry.get("request_attempts", 0)
            ) + 1
            try:
                payload = super()._get_url(url, params=params)
            except MassiveMultiAssetError as error:
                last_error = error
                if error.status_code is not None:
                    root_telemetry["http_status"] = int(error.status_code)
                root_telemetry["last_error"] = type(error).__name__
                if error.status_code == 429:
                    root_telemetry["rate_limited"] = True
                if not error.retryable or attempt >= self.reference_max_attempts:
                    if error.status_code in {401, 403}:
                        root_telemetry["failure_reason"] = "provider_auth_or_entitlement"
                    elif error.status_code is not None:
                        root_telemetry["failure_reason"] = "provider_http_error"
                    else:
                        root_telemetry["failure_reason"] = "provider_transport_error"
                    raise
                if error.status_code == 429:
                    delay = self.rate_limit_retry_seconds
                else:
                    delay = min(30.0, 2.0 ** (attempt - 1))
                root_telemetry["retry_count"] = int(
                    root_telemetry.get("retry_count", 0)
                ) + 1
                if delay > 0.0:
                    self._sleeper(delay)
            else:
                root_telemetry["http_status"] = 200
                return payload
        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse_date(value: object) -> date | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None

    @staticmethod
    def _sample_contract(
        *,
        ticker: str,
        product: str,
        venue: str,
        first: str,
        last: str,
        active: bool,
    ) -> dict[str, object]:
        return {
            "ticker": ticker,
            "product_code": product,
            "trading_venue": venue,
            "first_trade_date": first,
            "last_trade_date": last,
            "active": active,
        }

    @staticmethod
    def _finalize_root_telemetry(root_telemetry: dict[str, object]) -> None:
        if str(root_telemetry.get("failure_reason") or "") not in {"", "pending"}:
            return
        raw_count = int(root_telemetry.get("raw_result_count", 0))
        parsed_count = int(root_telemetry.get("parsed_contract_count", 0))
        matched_count = int(root_telemetry.get("root_matched_count", 0))
        valid_count = int(root_telemetry.get("point_in_time_valid_count", 0))
        usable_count = int(root_telemetry.get("usable_count", 0))
        schema_invalid_count = int(root_telemetry.get("schema_invalid_count", 0))
        pagination_complete = bool(root_telemetry.get("pagination_complete"))

        if not pagination_complete:
            reason = "pagination_incomplete"
        elif raw_count == 0:
            reason = "empty_provider_response"
        elif parsed_count == 0 or schema_invalid_count == raw_count:
            reason = "schema_parse_failure"
        elif matched_count == 0:
            reason = "root_mismatch"
        elif valid_count == 0:
            reason = "point_in_time_filter"
        elif usable_count == 0:
            reason = "usability_filter"
        else:
            reason = "ok"
        root_telemetry["failure_reason"] = reason

    @staticmethod
    def _compact_failure_telemetry(
        rows: Sequence[Mapping[str, object]],
    ) -> str:
        compact = [
            {
                "root": str(row.get("root") or ""),
                "status": row.get("http_status"),
                "raw": int(row.get("raw_result_count", 0)),
                "parsed": int(row.get("parsed_contract_count", 0)),
                "matched": int(row.get("root_matched_count", 0)),
                "valid": int(row.get("point_in_time_valid_count", 0)),
                "usable": int(row.get("usable_count", 0)),
                "reason": str(row.get("failure_reason") or "unknown"),
            }
            for row in rows
        ]
        return json.dumps(compact, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        if not self.api_key:
            raise MassiveMultiAssetError("Massive API key is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if isinstance(maximum_pages, bool) or not isinstance(maximum_pages, int):
            raise TypeError("maximum_pages must be an integer")
        if maximum_pages < 1:
            raise ValueError("maximum_pages must be positive")

        target_codes = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        query_codes: tuple[str | None, ...] = target_codes or (None,)
        result: dict[str, MassiveFuturesContract] = {}
        request_count = 0
        reference_date = as_of.astimezone(timezone.utc).date()
        reference_date_text = reference_date.isoformat()
        self._reference_telemetry = {}

        for target_code in query_codes:
            telemetry_key = target_code or "ALL"
            root_telemetry: dict[str, object] = {
                "root": telemetry_key,
                "request_path": _FUTURES_CONTRACT_PATH,
                "request_params": {
                    "active": "true",
                    "date": reference_date_text,
                    "limit": 1000,
                    **(
                        {"product_code": target_code}
                        if target_code is not None
                        else {}
                    ),
                },
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
            self._reference_telemetry[telemetry_key] = root_telemetry

            url = f"{MASSIVE_BASE_URL}{_FUTURES_CONTRACT_PATH}"
            # apiKey is deliberately kept out of request_params telemetry.
            params: dict[str, object] = {
                "date": reference_date_text,
                "active": "true",
                "limit": 1000,
                "apiKey": self.api_key,
            }
            if target_code is not None:
                params["product_code"] = target_code

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
                            "Massive futures contract response is missing results"
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
                        if target_code is not None and product != target_code:
                            continue
                        root_telemetry["root_matched_count"] = int(
                            root_telemetry["root_matched_count"]
                        ) + 1

                        raw_active = item.get("active", True)
                        active = (
                            raw_active.strip().lower() == "true"
                            if isinstance(raw_active, str)
                            else bool(raw_active)
                        )
                        point_in_time_valid = (
                            first_date <= reference_date <= last_date
                        )
                        if not point_in_time_valid:
                            continue
                        root_telemetry["point_in_time_valid_count"] = int(
                            root_telemetry["point_in_time_valid_count"]
                        ) + 1
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

                    next_url = (
                        str(payload.get("next_url") or "").strip()
                        if isinstance(payload, Mapping)
                        else ""
                    )
                    if not next_url:
                        root_telemetry["pagination_complete"] = True
                        break
                    root_telemetry["next_url_observed"] = True
                    parsed = urlparse(next_url)
                    if parsed.scheme != "https" or parsed.netloc != "api.massive.com":
                        root_telemetry["failure_reason"] = "invalid_pagination_url"
                        raise MassiveMultiAssetError(
                            "Massive futures pagination returned an invalid next_url"
                        )
                    url = next_url
                    params = {"apiKey": self.api_key}

                self._finalize_root_telemetry(root_telemetry)
                if not bool(root_telemetry["pagination_complete"]):
                    subject = target_code or "all products"
                    raise MassiveMultiAssetError(
                        "Massive futures contract pagination exceeded the completeness guard "
                        f"for {subject}"
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
        if target_codes:
            incomplete = tuple(
                row
                for row in telemetry
                if str(row.get("root") or "") in target_codes
                and int(row.get("usable_count", 0)) < 1
            )
            if incomplete:
                raise MassiveMultiAssetError(
                    "Massive futures reference coverage incomplete; "
                    "massive_futures_telemetry="
                    + self._compact_failure_telemetry(incomplete)
                )

        return tuple(result[key] for key in sorted(result))


__all__ = ["MassiveFuturesReferenceProvider"]
