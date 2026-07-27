"""Attempt-aware storage adapter for multi-asset paper execution retries."""

from __future__ import annotations

from typing import Any, Mapping

from portfolio.multi_asset_execution import (
    MultiAssetExecutionEventType,
    SQLiteMultiAssetPaperExecutionStore as _BaseStore,
)


class SQLiteMultiAssetPaperExecutionStore(_BaseStore):
    """Give every resumed batch attempt a distinct immutable start event."""

    def append(
        self,
        *,
        event_identifier: str,
        batch_identifier: str,
        event_type: MultiAssetExecutionEventType,
        occurred_at,
        payload: Mapping[str, Any],
    ) -> int:
        if event_type is MultiAssetExecutionEventType.BATCH_STARTED:
            previous = self.latest_batch(batch_identifier)
            attempt = 1 if previous is None else previous.attempt + 1
            event_identifier = f"{event_identifier}:attempt:{attempt}"
        return super().append(
            event_identifier=event_identifier,
            batch_identifier=batch_identifier,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
        )


__all__ = ["SQLiteMultiAssetPaperExecutionStore"]
