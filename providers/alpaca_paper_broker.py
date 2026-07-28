"""Paper-only Alpaca brokerage transport.

This module is deliberately restricted to ``paper-api.alpaca.markets``. It can
submit, inspect, and cancel paper orders and retrieve paper fill activities, but
it cannot be pointed at Alpaca's live brokerage endpoint and never grants
real-money authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from providers.alpaca_paper import (
    AlpacaPaperProviderError,
    AlpacaPaperSettings,
    create_alpaca_paper_client,
)


HttpRequest = Callable[..., Any]


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_decimal(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{field_name} must be numeric") from error
    if result <= 0.0:
        raise ValueError(f"{field_name} must be positive")
    return result


@dataclass(frozen=True, slots=True)
class AlpacaPaperOrderRequest:
    """One idempotent paper order request."""

    client_order_id: str
    symbol: str
    side: str
    order_type: str = "market"
    time_in_force: str = "day"
    quantity: float | None = None
    notional: float | None = None
    limit_price: float | None = None
    extended_hours: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            _text(self.client_order_id, field_name="client_order_id"),
        )
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        side = _text(self.side, field_name="side").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        object.__setattr__(self, "side", side)
        order_type = _text(self.order_type, field_name="order_type").lower()
        if order_type not in {"market", "limit"}:
            raise ValueError("paper broker supports market and limit orders only")
        object.__setattr__(self, "order_type", order_type)
        tif = _text(self.time_in_force, field_name="time_in_force").lower()
        if tif not in {"day", "gtc", "ioc"}:
            raise ValueError("unsupported paper time_in_force")
        object.__setattr__(self, "time_in_force", tif)
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("exactly one of quantity or notional is required")
        if self.quantity is not None:
            object.__setattr__(
                self,
                "quantity",
                _positive_decimal(self.quantity, field_name="quantity"),
            )
        if self.notional is not None:
            object.__setattr__(
                self,
                "notional",
                _positive_decimal(self.notional, field_name="notional"),
            )
        if self.limit_price is not None:
            object.__setattr__(
                self,
                "limit_price",
                _positive_decimal(self.limit_price, field_name="limit_price"),
            )
        if self.order_type == "market" and self.limit_price is not None:
            raise ValueError("market orders cannot include limit_price")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.notional is not None and (
            self.order_type != "market" or self.time_in_force not in {"day", "gtc"}
        ):
            raise ValueError("notional paper orders require a market order")
        if not isinstance(self.extended_hours, bool):
            raise TypeError("extended_hours must be a bool")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "time_in_force": self.time_in_force,
            "extended_hours": self.extended_hours,
        }
        if self.quantity is not None:
            payload["qty"] = format(self.quantity, ".12g")
        if self.notional is not None:
            payload["notional"] = format(self.notional, ".12g")
        if self.limit_price is not None:
            payload["limit_price"] = format(self.limit_price, ".12g")
        return payload


@dataclass(frozen=True, slots=True)
class AlpacaPaperApiResponse:
    payload: object
    request_id: str | None
    status_code: int


class AlpacaPaperBrokerClient:
    """Authenticated REST client restricted to Alpaca's paper brokerage domain."""

    def __init__(
        self,
        settings: AlpacaPaperSettings,
        *,
        http_request: HttpRequest | None = None,
    ) -> None:
        if not isinstance(settings, AlpacaPaperSettings):
            raise TypeError("settings must be AlpacaPaperSettings")
        settings.validate_provider_scope()
        self.settings = settings
        self._http_request = http_request or requests.request

    @property
    def headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.settings.api_key_id,
            "APCA-API-SECRET-KEY": self.settings.secret_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        json_payload: Mapping[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> AlpacaPaperApiResponse:
        self.settings.validate_provider_scope()
        try:
            response = self._http_request(
                method.upper(),
                self.settings.paper_base_url.rstrip("/") + path,
                headers=self.headers,
                params=dict(params or {}),
                json=None if json_payload is None else dict(json_payload),
                timeout=self.settings.timeout_seconds,
            )
        except requests.RequestException as error:
            raise AlpacaPaperProviderError(
                "Alpaca paper brokerage request failed"
            ) from error
        status = int(getattr(response, "status_code", 0))
        if allow_not_found and status == 404:
            return AlpacaPaperApiResponse(
                payload=None,
                request_id=None,
                status_code=status,
            )
        if status < 200 or status >= 300:
            message = ""
            try:
                body = response.json()
                if isinstance(body, Mapping):
                    message = str(body.get("message", "")).strip()
            except ValueError:
                message = ""
            detail = f": {message}" if message else ""
            raise AlpacaPaperProviderError(
                f"Alpaca paper brokerage returned HTTP {status}{detail}"
            )
        request_id = None
        headers = getattr(response, "headers", {})
        if isinstance(headers, Mapping):
            raw_request_id = headers.get("X-Request-ID") or headers.get(
                "x-request-id"
            )
            if isinstance(raw_request_id, str) and raw_request_id.strip():
                request_id = raw_request_id.strip()
        if status == 204:
            payload: object = None
        else:
            try:
                payload = response.json()
            except ValueError as error:
                raise AlpacaPaperProviderError(
                    "Alpaca paper brokerage returned invalid JSON"
                ) from error
        return AlpacaPaperApiResponse(
            payload=payload,
            request_id=request_id,
            status_code=status,
        )

    def account(self) -> Mapping[str, Any]:
        response = self._request("GET", "/v2/account")
        if not isinstance(response.payload, Mapping):
            raise AlpacaPaperProviderError(
                "Alpaca account response must be an object"
            )
        return response.payload

    def submit_order(
        self, request: AlpacaPaperOrderRequest
    ) -> tuple[Mapping[str, Any], str | None]:
        if not isinstance(request, AlpacaPaperOrderRequest):
            raise TypeError("request must be AlpacaPaperOrderRequest")
        response = self._request(
            "POST",
            "/v2/orders",
            json_payload=request.to_payload(),
        )
        if not isinstance(response.payload, Mapping):
            raise AlpacaPaperProviderError(
                "Alpaca order response must be an object"
            )
        return response.payload, response.request_id

    def order(self, order_id: str) -> Mapping[str, Any]:
        resolved = quote(_text(order_id, field_name="order_id"), safe="")
        response = self._request("GET", f"/v2/orders/{resolved}")
        if not isinstance(response.payload, Mapping):
            raise AlpacaPaperProviderError(
                "Alpaca order response must be an object"
            )
        return response.payload

    def cancel_order(self, order_id: str) -> str | None:
        resolved = quote(_text(order_id, field_name="order_id"), safe="")
        response = self._request("DELETE", f"/v2/orders/{resolved}")
        return response.request_id

    def position(self, symbol: str) -> Mapping[str, Any] | None:
        normalized = _text(symbol, field_name="symbol").upper()
        candidates = [normalized]
        if "/" in normalized:
            candidates.append(normalized.replace("/", ""))
        for candidate in dict.fromkeys(candidates):
            resolved = quote(candidate, safe="")
            response = self._request(
                "GET",
                f"/v2/positions/{resolved}",
                allow_not_found=True,
            )
            if response.payload is None:
                continue
            if not isinstance(response.payload, Mapping):
                raise AlpacaPaperProviderError(
                    "Alpaca position response must be an object"
                )
            return response.payload
        return None

    def fill_activities(
        self,
        *,
        after: str | None = None,
        until: str | None = None,
        page_size: int = 100,
    ) -> tuple[Mapping[str, Any], ...]:
        if isinstance(page_size, bool) or not isinstance(page_size, int):
            raise TypeError("page_size must be an integer")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, object] = {
            "direction": "asc",
            "page_size": page_size,
        }
        if after:
            params["after"] = _text(after, field_name="after")
        if until:
            params["until"] = _text(until, field_name="until")
        response = self._request(
            "GET",
            "/v2/account/activities/FILL",
            params=params,
        )
        if not isinstance(response.payload, list) or not all(
            isinstance(item, Mapping) for item in response.payload
        ):
            raise AlpacaPaperProviderError(
                "Alpaca fill activities must be an array"
            )
        return tuple(response.payload)


def create_alpaca_paper_broker_client(
    *,
    http_request: HttpRequest | None = None,
) -> AlpacaPaperBrokerClient:
    authenticated = create_alpaca_paper_client()
    return AlpacaPaperBrokerClient(
        authenticated.settings,
        http_request=http_request,
    )


__all__ = [
    "AlpacaPaperApiResponse",
    "AlpacaPaperBrokerClient",
    "AlpacaPaperOrderRequest",
    "create_alpaca_paper_broker_client",
]
