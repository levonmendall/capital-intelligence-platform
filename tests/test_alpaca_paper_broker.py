from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from governance.provider_activation import (
    ProviderActivation,
    ProviderActivationError,
    SQLiteProviderActivationStore,
)
from operations.alpaca_paper_broker import (
    AlpacaPaperBrokerExecutor,
    AlpacaPaperBrokerIntegrityError,
    SQLiteAlpacaPaperBrokerStore,
)
from providers.alpaca_paper import AlpacaPaperProviderError, AlpacaPaperSettings
from providers.alpaca_paper_broker import (
    AlpacaPaperBrokerClient,
    AlpacaPaperOrderRequest,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 28, 21, 0, tzinfo=timezone.utc)


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


class _PaperBrokerApi:
    def __init__(self, *, duplicate_fill: bool = False) -> None:
        self.duplicate_fill = duplicate_fill
        self.orders: dict[str, dict[str, Any]] = {}
        self.activities: list[dict[str, Any]] = []
        self.position_quantity = 0.0
        self.submitted_payloads: list[dict[str, Any]] = []
        self.request_count = 0

    def __call__(self, method: str, url: str, **kwargs: Any) -> _Response:
        assert url.startswith("https://paper-api.alpaca.markets/")
        self.request_count += 1
        if method == "GET" and url.endswith("/v2/account"):
            return _Response(
                {
                    "id": "paper-account",
                    "status": "ACTIVE",
                    "trading_blocked": False,
                    "account_blocked": False,
                }
            )
        if method == "POST" and url.endswith("/v2/orders"):
            payload = dict(kwargs["json"])
            self.submitted_payloads.append(payload)
            order_number = len(self.orders) + 1
            order_id = f"paper-order-{order_number}"
            side = str(payload["side"])
            price = 100.0
            quantity = (
                float(payload["qty"])
                if "qty" in payload
                else round(float(payload["notional"]) / price, 12)
            )
            self.position_quantity += quantity if side == "buy" else -quantity
            if abs(self.position_quantity) < 1e-12:
                self.position_quantity = 0.0
            order = {
                "id": order_id,
                "client_order_id": payload["client_order_id"],
                "symbol": payload["symbol"],
                "side": side,
                "status": "filled",
                "qty": str(quantity if "qty" in payload else ""),
                "notional": str(payload.get("notional", "")),
                "filled_qty": str(quantity),
                "filled_avg_price": str(price),
                "submitted_at": NOW.isoformat(),
                "filled_at": (NOW + timedelta(seconds=1)).isoformat(),
            }
            self.orders[order_id] = order
            activity = {
                "id": f"fill-{order_number}",
                "activity_type": "FILL",
                "order_id": order_id,
                "symbol": payload["symbol"],
                "side": side,
                "qty": str(quantity),
                "price": str(price),
                "transaction_time": (NOW + timedelta(seconds=1)).isoformat(),
            }
            self.activities.append(activity)
            if self.duplicate_fill:
                self.activities.append(dict(activity))
            return _Response(order, request_id=f"request-{order_number}")
        if method == "GET" and "/v2/orders/" in url:
            return _Response(self.orders[url.rsplit("/", 1)[-1]])
        if method == "DELETE" and "/v2/orders/" in url:
            return _Response(None, status_code=204, request_id="cancel-request")
        if method == "GET" and "/v2/positions/" in url:
            if self.position_quantity == 0.0:
                return _Response({"message": "position does not exist"}, status_code=404)
            return _Response(
                {
                    "symbol": "BTC/USD",
                    "qty": str(self.position_quantity),
                }
            )
        if method == "GET" and url.endswith("/v2/account/activities/FILL"):
            return _Response(list(self.activities))
        raise AssertionError(f"unexpected request {method} {url}")


def _activation() -> ProviderActivation:
    payload = json.loads(
        (ROOT / "config" / "alpaca_paper_broker_activation.json").read_text(
            encoding="utf-8"
        )
    )
    return ProviderActivation.from_dict(payload)


def _executor(
    tmp_path: Path,
    *,
    api: _PaperBrokerApi | None = None,
    activate: bool = True,
) -> tuple[AlpacaPaperBrokerExecutor, SQLiteAlpacaPaperBrokerStore, _PaperBrokerApi]:
    fake = api or _PaperBrokerApi()
    client = AlpacaPaperBrokerClient(
        AlpacaPaperSettings(
            api_key_id="paper-key",
            secret_key="paper-secret",
        ),
        http_request=fake,
    )
    activation_store = SQLiteProviderActivationStore(tmp_path / "provider.db")
    if activate:
        activation_store.append(_activation())
    event_store = SQLiteAlpacaPaperBrokerStore(tmp_path / "broker.db")
    return (
        AlpacaPaperBrokerExecutor(
            client=client,
            activation_store=activation_store,
            event_store=event_store,
            sleep=lambda _: None,
        ),
        event_store,
        fake,
    )


def test_governed_neutral_round_trip_submits_and_reconciles(tmp_path: Path) -> None:
    executor, store, api = _executor(tmp_path)

    report = executor.round_trip_smoke(
        symbol="BTC/USD",
        notional=1.0,
        evaluated_at=NOW,
    )

    assert report.reconciled
    assert report.net_quantity_change == pytest.approx(0.0)
    assert report.buy_reconciliation.reconciled
    assert report.sell_reconciliation.reconciled
    assert len(api.submitted_payloads) == 2
    assert api.submitted_payloads[0]["side"] == "buy"
    assert api.submitted_payloads[0]["notional"] == "1"
    assert api.submitted_payloads[1]["side"] == "sell"
    assert api.submitted_payloads[1]["qty"] == "0.01"
    assert all(payload["type"] == "market" for payload in api.submitted_payloads)
    assert store.verify_integrity()
    assert not report.real_money_authorized


def test_missing_provider_activation_blocks_before_order_submission(tmp_path: Path) -> None:
    executor, _, api = _executor(tmp_path, activate=False)

    with pytest.raises(ProviderActivationError, match="activation is unavailable"):
        executor.submit_and_reconcile(
            AlpacaPaperOrderRequest(
                client_order_id="blocked-order",
                symbol="BTC/USD",
                side="buy",
                notional=1.0,
                time_in_force="gtc",
            ),
            evaluated_at=NOW,
        )

    assert api.submitted_payloads == []


def test_duplicate_fill_activities_fail_reconciliation(tmp_path: Path) -> None:
    executor, _, _ = _executor(
        tmp_path,
        api=_PaperBrokerApi(duplicate_fill=True),
    )

    report = executor.submit_and_reconcile(
        AlpacaPaperOrderRequest(
            client_order_id="duplicate-fill-test",
            symbol="BTC/USD",
            side="buy",
            notional=1.0,
            time_in_force="gtc",
        ),
        evaluated_at=NOW,
        activity_timeout_seconds=1,
    )

    assert not report.reconciled
    assert any("duplicate" in item for item in report.blockers)
    assert any("quantity" in item for item in report.blockers)


def test_live_alpaca_broker_endpoint_is_rejected() -> None:
    settings = AlpacaPaperSettings(
        api_key_id="key",
        secret_key="secret",
        paper_base_url="https://api.alpaca.markets",
    )

    with pytest.raises(AlpacaPaperProviderError, match="paper endpoint"):
        AlpacaPaperBrokerClient(settings)


def test_order_request_is_idempotent_and_scoped() -> None:
    request = AlpacaPaperOrderRequest(
        client_order_id="capital-intelligence-order-1",
        symbol="spy",
        side="buy",
        notional=5.0,
        order_type="market",
        time_in_force="day",
    )

    assert request.to_payload() == {
        "client_order_id": "capital-intelligence-order-1",
        "symbol": "SPY",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "extended_hours": False,
        "notional": "5",
    }


def test_broker_event_store_is_append_only_and_tamper_evident(tmp_path: Path) -> None:
    executor, store, _ = _executor(tmp_path)
    report = executor.submit_and_reconcile(
        AlpacaPaperOrderRequest(
            client_order_id="integrity-test",
            symbol="BTC/USD",
            side="buy",
            notional=1.0,
            time_in_force="gtc",
        ),
        evaluated_at=NOW,
    )
    assert report.reconciled
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE alpaca_paper_broker_events SET payload_json='{}' WHERE sequence=1"
            )
        connection.execute("DROP TRIGGER alpaca_paper_broker_events_no_update")
        connection.execute(
            "UPDATE alpaca_paper_broker_events SET payload_json='{}' WHERE sequence=1"
        )

    with pytest.raises(AlpacaPaperBrokerIntegrityError):
        store.verify_integrity()
