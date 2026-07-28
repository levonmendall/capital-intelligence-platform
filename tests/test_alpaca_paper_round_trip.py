from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from governance.provider_activation import ProviderActivation, SQLiteProviderActivationStore
from operations.alpaca_paper_broker import SQLiteAlpacaPaperBrokerStore
from operations.alpaca_paper_round_trip import (
    POSITION_TOLERANCE,
    FeeAwareAlpacaPaperBrokerExecutor,
)
from providers.alpaca_paper import AlpacaPaperSettings
from providers.alpaca_paper_broker import AlpacaPaperBrokerClient


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 28, 22, 15, tzinfo=timezone.utc)


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        request_id: str | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = {} if request_id is None else {"X-Request-ID": request_id}

    def json(self) -> object:
        return self._payload


class _FeeAwarePaperApi:
    def __init__(self) -> None:
        self.opening_available = Decimal("0.000300000")
        self.available = self.opening_available
        self.orders: dict[str, dict[str, Any]] = {}
        self.activities: list[dict[str, Any]] = []
        self.submitted: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> _Response:
        if method == "GET" and url.endswith("/v2/account"):
            return _Response(
                {
                    "status": "ACTIVE",
                    "trading_blocked": False,
                    "account_blocked": False,
                }
            )
        if method == "GET" and "/v2/positions/" in url:
            return _Response(
                {
                    "symbol": "BTC/USD",
                    "qty": str(self.available),
                    "qty_available": str(self.available),
                }
            )
        if method == "POST" and url.endswith("/v2/orders"):
            request = dict(kwargs["json"])
            self.submitted.append(request)
            order_number = len(self.submitted)
            order_id = f"fee-order-{order_number}"
            side = str(request["side"])
            if side == "buy":
                gross_quantity = Decimal("0.000153301")
                net_available = Decimal("0.000152917")
                self.available += net_available
                fill_quantity = gross_quantity
            else:
                fill_quantity = Decimal(str(request["qty"]))
                self.available -= fill_quantity
            order = {
                "id": order_id,
                "client_order_id": request["client_order_id"],
                "symbol": request["symbol"],
                "side": side,
                "status": "filled",
                "qty": str(request.get("qty", "")),
                "notional": str(request.get("notional", "")),
                "filled_qty": str(fill_quantity),
                "filled_avg_price": "65231.15",
                "submitted_at": NOW.isoformat(),
                "filled_at": (NOW + timedelta(seconds=1)).isoformat(),
            }
            self.orders[order_id] = order
            self.activities.append(
                {
                    "id": f"fee-fill-{order_number}",
                    "activity_type": "FILL",
                    "order_id": order_id,
                    "symbol": "BTC/USD",
                    "side": side,
                    "qty": str(fill_quantity),
                    "price": "65231.15",
                    "transaction_time": (NOW + timedelta(seconds=1)).isoformat(),
                }
            )
            return _Response(order, request_id=f"fee-request-{order_number}")
        if method == "GET" and "/v2/orders/" in url:
            return _Response(self.orders[url.rsplit("/", 1)[-1]])
        if method == "GET" and url.endswith("/v2/account/activities/FILL"):
            return _Response(list(self.activities))
        if method == "DELETE" and "/v2/orders/" in url:
            return _Response(None, status_code=204)
        raise AssertionError(f"unexpected request {method} {url}")


def _activation() -> ProviderActivation:
    payload = json.loads(
        (ROOT / "config" / "alpaca_paper_broker_activation.json").read_text(
            encoding="utf-8"
        )
    )
    return ProviderActivation.from_dict(payload)


def test_round_trip_sells_net_available_crypto_and_preserves_opening_position(
    tmp_path: Path,
) -> None:
    api = _FeeAwarePaperApi()
    opening_available = float(api.opening_available)
    client = AlpacaPaperBrokerClient(
        AlpacaPaperSettings(api_key_id="paper-key", secret_key="paper-secret"),
        http_request=api,
    )
    activation_store = SQLiteProviderActivationStore(tmp_path / "provider.db")
    activation_store.append(_activation())
    event_store = SQLiteAlpacaPaperBrokerStore(tmp_path / "broker.db")
    executor = FeeAwareAlpacaPaperBrokerExecutor(
        client=client,
        activation_store=activation_store,
        event_store=event_store,
        sleep=lambda _: None,
    )

    report = executor.round_trip_smoke(
        symbol="BTC/USD",
        notional=10.0,
        evaluated_at=NOW,
    )

    tolerance = float(POSITION_TOLERANCE)
    assert report.reconciled
    assert report.opening_quantity == pytest.approx(opening_available, abs=tolerance)
    assert report.closing_quantity == pytest.approx(opening_available, abs=tolerance)
    assert report.net_quantity_change == pytest.approx(0.0, abs=tolerance)
    assert api.submitted[0]["notional"] == "10"
    assert api.submitted[1]["qty"] == "0.000152917"
    assert event_store.verify_integrity()


def test_fee_aware_round_trip_requires_crypto_pair(tmp_path: Path) -> None:
    api = _FeeAwarePaperApi()
    client = AlpacaPaperBrokerClient(
        AlpacaPaperSettings(api_key_id="paper-key", secret_key="paper-secret"),
        http_request=api,
    )
    activation_store = SQLiteProviderActivationStore(tmp_path / "provider.db")
    activation_store.append(_activation())
    executor = FeeAwareAlpacaPaperBrokerExecutor(
        client=client,
        activation_store=activation_store,
        event_store=SQLiteAlpacaPaperBrokerStore(tmp_path / "broker.db"),
        sleep=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="crypto pair"):
        executor.round_trip_smoke(symbol="SPY", notional=10.0, evaluated_at=NOW)
