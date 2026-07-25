"""Delivery dispatch extension that safely hydrates email recipients."""

from __future__ import annotations

from typing import Any

from delivery.models import AlertChannel
from delivery.service import AlertDeliveryService as BaseAlertDeliveryService


class _EmailDeliveryEnvelope:
    def __init__(self, delivery: Any, email_address: str) -> None:
        self._delivery = delivery
        self.email_address = email_address

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delivery, name)


class AlertDeliveryService(BaseAlertDeliveryService):
    """Dispatch pending deliveries with recipients resolved at send time."""

    def dispatch_pending(self, *, limit: int = 100) -> tuple[Any, ...]:
        completed: list[Any] = []
        now = self._clock()
        for delivery in self.store.pending(now=now, limit=limit):
            try:
                if delivery.channel is AlertChannel.IN_APP:
                    detail = "In-app alert is available in the authenticated inbox."
                else:
                    dispatcher = self.dispatchers.get(delivery.channel)
                    if dispatcher is None:
                        raise RuntimeError(
                            f"no dispatcher is configured for {delivery.channel.value}"
                        )
                    preference = self.store.get_preference(delivery.user_id)
                    if preference.email_address is None:
                        raise RuntimeError("email delivery is missing a recipient")
                    dispatcher(
                        _EmailDeliveryEnvelope(
                            delivery,
                            preference.email_address,
                        )
                    )
                    detail = f"{delivery.channel.value} delivery succeeded."
            except Exception as error:
                completed.append(
                    self.store.record_attempt(
                        delivery.delivery_id,
                        success=False,
                        detail=str(error),
                        now=now,
                        maximum_attempts=self.maximum_attempts,
                        base_retry_delay=self.base_retry_delay,
                    )
                )
            else:
                completed.append(
                    self.store.record_attempt(
                        delivery.delivery_id,
                        success=True,
                        detail=detail,
                        now=now,
                        maximum_attempts=self.maximum_attempts,
                        base_retry_delay=self.base_retry_delay,
                    )
                )
        return tuple(completed)


__all__ = ["AlertDeliveryService"]
