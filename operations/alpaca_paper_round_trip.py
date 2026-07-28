"""Fee-aware neutral Alpaca paper round-trip verification.

Crypto buy fees reduce the received asset quantity. The broker may therefore
report a gross filled quantity that is slightly larger than the quantity
available to sell. This executor preserves any pre-existing paper position and
closes only the newly available net quantity, rounded down to Alpaca's current
nine-decimal crypto quantity precision.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from operations.alpaca_paper_broker import (
    AlpacaPaperBrokerError,
    AlpacaPaperBrokerExecutor,
    AlpacaPaperRoundTripReport,
)
from providers.alpaca_paper_broker import AlpacaPaperOrderRequest


CRYPTO_QUANTITY_INCREMENT = Decimal("0.000000001")
POSITION_TOLERANCE = Decimal("0.000000001")


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _decimal(value: object, *, field_name: str, default: Decimal | None = None) -> Decimal:
    if value is None or value == "":
        if default is None:
            raise ValueError(f"{field_name} is unavailable")
        return default
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise TypeError(f"{field_name} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _usable_position_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _available_quantity(position: object) -> Decimal:
    if position is None:
        return Decimal("0")
    if not isinstance(position, dict):
        try:
            source = dict(position)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise TypeError("position must be a mapping") from error
    else:
        source = position
    candidate = source.get("qty_available")
    if not _usable_position_value(candidate):
        candidate = source.get("qty")
    return _decimal(
        candidate,
        field_name="available position quantity",
        default=Decimal("0"),
    )


def _round_down_crypto_quantity(value: Decimal) -> Decimal:
    if value <= 0:
        raise AlpacaPaperBrokerError("net available crypto quantity is not positive")
    rounded = value.quantize(CRYPTO_QUANTITY_INCREMENT, rounding=ROUND_DOWN)
    if rounded <= 0:
        raise AlpacaPaperBrokerError(
            "net available crypto quantity is below Alpaca's minimum increment"
        )
    return rounded


class FeeAwareAlpacaPaperBrokerExecutor(AlpacaPaperBrokerExecutor):
    """Perform a neutral paper round trip using net available crypto quantity."""

    def _wait_for_available_position(
        self,
        *,
        symbol: str,
        greater_than: Decimal | None = None,
        target: Decimal | None = None,
        timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
    ) -> Decimal:
        if greater_than is None and target is None:
            raise ValueError("greater_than or target is required")
        deadline = time.monotonic() + timeout_seconds
        latest = Decimal("0")
        while time.monotonic() < deadline:
            latest = _available_quantity(self.client.position(symbol))
            if greater_than is not None and latest > greater_than + POSITION_TOLERANCE:
                return latest
            if target is not None and abs(latest - target) <= POSITION_TOLERANCE:
                return latest
            self.sleep(poll_interval_seconds)
        return latest

    def round_trip_smoke(
        self,
        *,
        symbol: str = "BTC/USD",
        notional: float = 10.0,
        evaluated_at: datetime | None = None,
    ) -> AlpacaPaperRoundTripReport:
        now = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        normalized_symbol = _text(symbol, field_name="symbol").upper()
        amount = _decimal(notional, field_name="notional")
        if amount < Decimal("10"):
            raise AlpacaPaperBrokerError(
                "Alpaca paper crypto smoke notional must be at least $10.00"
            )
        if "/" not in normalized_symbol:
            raise AlpacaPaperBrokerError(
                "fee-aware neutral smoke currently requires a crypto pair"
            )

        opening_available = _available_quantity(
            self.client.position(normalized_symbol)
        )
        run_material = f"{normalized_symbol}|{amount}|{now.isoformat()}"
        run_id = hashlib.sha256(run_material.encode("utf-8")).hexdigest()[:20]

        buy = self.submit_and_reconcile(
            AlpacaPaperOrderRequest(
                client_order_id=f"cip-smoke-buy-{run_id}",
                symbol=normalized_symbol,
                side="buy",
                order_type="market",
                time_in_force="gtc",
                notional=float(amount),
            ),
            evaluated_at=now,
        )
        if not buy.reconciled:
            raise AlpacaPaperBrokerError(
                "paper smoke buy failed reconciliation: " + "; ".join(buy.blockers)
            )

        after_buy_available = self._wait_for_available_position(
            symbol=normalized_symbol,
            greater_than=opening_available,
        )
        acquired_available = after_buy_available - opening_available
        if acquired_available <= 0:
            raise AlpacaPaperBrokerError(
                "net available crypto quantity is not positive after waiting for "
                "the broker position to update"
            )
        sell_quantity = _round_down_crypto_quantity(acquired_available)

        sell = self.submit_and_reconcile(
            AlpacaPaperOrderRequest(
                client_order_id=f"cip-smoke-sell-{run_id}",
                symbol=normalized_symbol,
                side="sell",
                order_type="market",
                time_in_force="gtc",
                quantity=float(sell_quantity),
            ),
            evaluated_at=datetime.now(timezone.utc),
        )

        closing_available = self._wait_for_available_position(
            symbol=normalized_symbol,
            target=opening_available,
        )
        net_change = closing_available - opening_available
        blockers: list[str] = []
        if not sell.reconciled:
            blockers.append("sell order did not reconcile")
        if abs(net_change) > POSITION_TOLERANCE:
            blockers.append(
                "paper smoke did not return available broker quantity to its opening value"
            )

        return AlpacaPaperRoundTripReport(
            identifier=f"alpaca-paper-round-trip:{run_id}",
            evaluated_at=datetime.now(timezone.utc),
            symbol=normalized_symbol,
            opening_quantity=float(opening_available),
            closing_quantity=float(closing_available),
            net_quantity_change=float(net_change),
            buy_reconciliation=buy,
            sell_reconciliation=sell,
            reconciled=not blockers,
            blockers=tuple(blockers),
        )


__all__ = [
    "CRYPTO_QUANTITY_INCREMENT",
    "FeeAwareAlpacaPaperBrokerExecutor",
    "POSITION_TOLERANCE",
]
