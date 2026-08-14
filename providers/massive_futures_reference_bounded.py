"""Server-bounded current fallback for Massive futures reference discovery.

The strict dated provider remains the canonical path. The resilient provider owns the
near-current compatibility fallback when Massive accepts the dated request but returns
no records. This wrapper first narrows that fallback using the original as-of trade
window and the governed outright-contract type. If Massive returns an empty HTTP-200
response for both that query and the product-scoped single-contract index, it retries
the same product-scoped index without a provider-side type filter. Massive documents
that contract type may be single, combo, or empty; the untyped retry therefore rejects
explicit combo/unknown types locally and admits only single or empty-type rows into the
inherited root, active, and point-in-time validation. Existing pagination and configured-
root completeness checks remain fail closed.

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
from providers.massive_multi_asset import MassiveFuturesContract


class MassiveFuturesReferenceProvider(_ResilientMassiveFuturesReferenceProvider):
    """Apply governed server-side bounds to the near-current compatibility fallback."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._fallback_reference_date: str | None = None

    @staticmethod
    def _locally_filter_contract_type(
        payload: Mapping[str, Any],
        *,
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        """Reject explicit non-outright types while preserving provider-empty type rows.

        Massive's contract reference schema permits ``type`` to be ``single``, ``combo``,
        or empty. The compatibility retry is only reached after the provider's
        ``type=single`` index returned an empty HTTP-200 response, so missing/empty type
        cannot safely be interpreted as a combo. Those rows still have to pass the
        inherited product-root, first/last-trade-date, active, schema, and pagination
        completeness checks before they are usable.
        """

        raw = payload.get("results")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return payload

        filtered: list[object] = []
        rejected = 0
        for item in raw:
            if isinstance(item, Mapping):
                contract_type = str(item.get("type") or "").strip().lower()
                if contract_type and contract_type != "single":
                    rejected += 1
                    continue
            filtered.append(item)

        root_telemetry["provider_raw_result_count"] = int(
            root_telemetry.get("provider_raw_result_count", 0)
        ) + len(raw)
        root_telemetry["contract_type_rejected_count"] = int(
            root_telemetry.get("contract_type_rejected_count", 0)
        ) + rejected

        if len(filtered) == len(raw):
            return payload
        filtered_payload = dict(payload)
        filtered_payload["results"] = filtered
        return filtered_payload

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        reference_date = self._fallback_reference_date

        # Pagination requests for the final untyped compatibility query carry only the
        # credential parameter. Keep applying the same local contract-type gate on those
        # pages before the inherited point-in-time parser sees them.
        if (
            root_telemetry.get("query_mode")
            == "current_untyped_index_with_local_contract_type_validation"
            and "product_code" not in params
        ):
            payload = super()._reference_get(
                url,
                params=params,
                root_telemetry=root_telemetry,
            )
            return self._locally_filter_contract_type(
                payload,
                root_telemetry=root_telemetry,
            )

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
        # Prefer the provider-side outright filter first. This is efficient when Massive
        # has populated type metadata and prevents combo rows from consuming pagination.
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
        root_telemetry["untyped_empty_retry_used"] = False
        root_telemetry["local_contract_type_validation"] = False
        root_telemetry["provider_raw_result_count"] = 0
        root_telemetry["contract_type_rejected_count"] = 0

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

        # Retry only the empty bounded response against the product-scoped
        # single-contract index. The inherited provider still applies the original
        # first_trade_date <= as_of <= last_trade_date rule locally before acceptance.
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

        index_payload = super()._reference_get(
            url,
            params=index_params,
            root_telemetry=root_telemetry,
        )
        index_raw = (
            index_payload.get("results")
            if isinstance(index_payload, Mapping)
            else None
        )
        if not (
            isinstance(index_raw, Sequence)
            and not isinstance(index_raw, (str, bytes))
            and len(index_raw) == 0
        ):
            return index_payload

        # Telemetry #512 showed that some configured roots return HTTP 200 with zero
        # rows from the provider's type=single index. Massive documents that the type
        # field can also be empty. Retry only this exact empty condition without the
        # server-side type predicate, then reject explicit combo/unknown types locally.
        if self.minimum_call_interval_seconds > 0.0:
            self._sleeper(self.minimum_call_interval_seconds)
        untyped_params = dict(index_params)
        untyped_params.pop("type", None)

        if isinstance(sanitized, dict):
            sanitized.clear()
            sanitized.update(
                {
                    "limit": untyped_params.get("limit", 1000),
                    "product_code": untyped_params.get("product_code"),
                }
            )
        root_telemetry["query_mode"] = (
            "current_untyped_index_with_local_contract_type_validation"
        )
        root_telemetry["untyped_empty_retry_used"] = True
        root_telemetry["server_side_contract_type_bound"] = False
        root_telemetry["local_contract_type_validation"] = True

        untyped_payload = super()._reference_get(
            url,
            params=untyped_params,
            root_telemetry=root_telemetry,
        )
        return self._locally_filter_contract_type(
            untyped_payload,
            root_telemetry=root_telemetry,
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
            return super().futures_contracts(
                as_of=as_of,
                product_codes=product_codes,
                maximum_pages=maximum_pages,
            )
        finally:
            self._fallback_reference_date = previous_reference_date


__all__ = ["MassiveFuturesReferenceProvider"]
