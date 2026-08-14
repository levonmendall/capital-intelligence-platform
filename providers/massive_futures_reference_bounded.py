"""Server-bounded current fallback for Massive futures reference discovery.

The strict dated provider remains the canonical path. The resilient provider owns the
near-current compatibility fallback when Massive accepts the dated request but returns
no records. This wrapper narrows only that fallback at the provider using the original
as-of trade window and the governed outright-contract type before pagination starts,
while the inherited local point-in-time checks remain authoritative and fail closed.

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

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        bounded_params = params
        reference_date = self._fallback_reference_date

        # Only the first request of the resilient current fallback carries explicit
        # product/date-window parameters. Pagination requests use Massive's returned
        # cursor URL and therefore intentionally keep only the credential parameter.
        if (
            reference_date
            and root_telemetry.get("query_mode") == "current_active_without_date"
            and "product_code" in params
            and "date" not in params
        ):
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

        return super()._reference_get(
            url,
            params=bounded_params,
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
