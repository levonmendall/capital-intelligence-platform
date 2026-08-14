"""Server-bounded current fallback for Massive futures reference discovery.

The strict dated provider remains the canonical path. The resilient provider owns the
near-current compatibility fallback when Massive accepts the dated request but returns
no records. This wrapper first narrows that fallback using the original as-of trade
window and the governed outright-contract type. If Massive returns an empty HTTP-200
response for that combined query, it retries the same product-scoped single-contract
index without the provider-side active/trade-window filters and leaves the inherited
local point-in-time validation authoritative and fail closed.

For near-current multi-root requests each configured root is resolved independently:
strict dated data is retained for roots that succeed, while only roots whose strict
response is empty are eligible for the existing bounded compatibility fallback. Complete
configured-root coverage is still required before any result is returned.

No investment, construction, execution, threshold, market-scope, or real-money behavior
is changed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from providers.massive_futures_reference_resilient import (
    MassiveFuturesReferenceProvider as _ResilientMassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import (
    MassiveFuturesContract,
    MassiveMultiAssetError,
)


class MassiveFuturesReferenceProvider(_ResilientMassiveFuturesReferenceProvider):
    """Apply governed server-side bounds to the near-current compatibility fallback."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._fallback_reference_date: str | None = None

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        reference_date = self._fallback_reference_date

        # Only the first request of the resilient current fallback carries explicit
        # product/date-window parameters. Pagination requests use Massive's returned
        # cursor URL and therefore intentionally keep only the credential parameter.
        if not (
            reference_date
            and root_telemetry.get("query_mode") == "current_active_without_date"
            and "product_code" in params
            and "date" not in params
        ):
            return super()._reference_get(
                url,
                params=params,
                root_telemetry=root_telemetry,
            )

        bounded_params = dict(params)
        bounded_params["first_trade_date.lte"] = reference_date
        bounded_params["last_trade_date.gte"] = reference_date
        # The governed futures lane represents outright dated futures only. Massive
        # returns both single and combo contracts when type is omitted; requesting
        # singles prevents non-investable spread/combo rows from consuming the
        # completeness pagination budget without changing configured product roots.
        bounded_params["type"] = "single"

        sanitized = root_telemetry.get("request_params")
        if isinstance(sanitized, dict):
            sanitized["first_trade_date.lte"] = reference_date
            sanitized["last_trade_date.gte"] = reference_date
            sanitized["type"] = "single"
        root_telemetry["query_mode"] = "current_active_single_trade_window_without_date"
        root_telemetry["server_side_point_in_time_bound"] = True
        root_telemetry["server_side_contract_type_bound"] = True
        root_telemetry["bounded_empty_retry_used"] = False

        payload = super()._reference_get(
            url,
            params=bounded_params,
            root_telemetry=root_telemetry,
        )
        raw = payload.get("results") if isinstance(payload, Mapping) else None
        if not (
            isinstance(raw, Sequence)
            and not isinstance(raw, (str, bytes))
            and len(raw) == 0
        ):
            return payload

        # Production telemetry proved that Massive can return HTTP 200 with no records
        # for the otherwise valid combination of active=true, type=single, and current
        # trade-window modifiers. Retry only that empty response against the
        # product-scoped outright-contract index. This avoids reintroducing combo/spread
        # pagination pressure while the resilient provider still applies the original
        # first_trade_date <= as_of <= last_trade_date rule locally before accepting any
        # contract. The existing pagination cap and configured-root completeness checks
        # remain authoritative.
        if self.minimum_call_interval_seconds > 0.0:
            self._sleeper(self.minimum_call_interval_seconds)
        index_params = dict(params)
        index_params.pop("active", None)
        index_params["type"] = "single"

        if isinstance(sanitized, dict):
            sanitized.clear()
            sanitized.update(
                {
                    "limit": index_params.get("limit", 1000),
                    "product_code": index_params.get("product_code"),
                    "type": "single",
                }
            )
        root_telemetry["query_mode"] = "current_single_index_without_active_window"
        root_telemetry["bounded_empty_retry_used"] = True
        root_telemetry["server_side_point_in_time_bound"] = False
        root_telemetry["local_point_in_time_validation"] = True
        root_telemetry["server_side_contract_type_bound"] = True

        return super()._reference_get(
            url,
            params=index_params,
            root_telemetry=root_telemetry,
        )

    def _near_current_root_scoped_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str],
        maximum_pages: int,
    ) -> tuple[MassiveFuturesContract, ...]:
        """Resolve near-current configured roots independently without weakening coverage."""

        target_codes = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        contracts_by_ticker: dict[str, MassiveFuturesContract] = {}
        telemetry_by_root: dict[str, dict[str, object]] = {}

        for index, target_code in enumerate(target_codes):
            # A singleton strict call owns no inter-root pacing, so preserve the strict
            # provider's governed call interval explicitly between configured roots.
            if index and self.minimum_call_interval_seconds > 0.0:
                self._sleeper(self.minimum_call_interval_seconds)

            try:
                root_contracts = super().futures_contracts(
                    as_of=as_of,
                    product_codes=(target_code,),
                    maximum_pages=maximum_pages,
                )
            except MassiveMultiAssetError:
                for row in self.reference_telemetry:
                    root = str(row.get("root") or "").strip().upper()
                    if root:
                        telemetry_by_root[root] = dict(row)
                self._reference_telemetry = telemetry_by_root
                raise

            for row in self.reference_telemetry:
                root = str(row.get("root") or "").strip().upper()
                if root:
                    telemetry_by_root[root] = dict(row)
            for contract in root_contracts:
                contracts_by_ticker[contract.ticker] = contract

        self._reference_telemetry = telemetry_by_root
        return tuple(
            contracts_by_ticker[ticker] for ticker in sorted(contracts_by_ticker)
        )

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        previous_reference_date = self._fallback_reference_date
        self._fallback_reference_date = as_of.astimezone(timezone.utc).date().isoformat()
        try:
            target_codes = tuple(
                sorted(
                    {
                        str(item).strip().upper()
                        for item in product_codes
                        if str(item).strip()
                    }
                )
            )
            if len(target_codes) > 1 and self._current_fallback_allowed(as_of):
                return self._near_current_root_scoped_contracts(
                    as_of=as_of,
                    product_codes=target_codes,
                    maximum_pages=maximum_pages,
                )
            return super().futures_contracts(
                as_of=as_of,
                product_codes=product_codes,
                maximum_pages=maximum_pages,
            )
        finally:
            self._fallback_reference_date = previous_reference_date


__all__ = ["MassiveFuturesReferenceProvider"]
