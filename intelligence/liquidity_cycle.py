"""Compatibility scheduler wrapper for the Global Liquidity engine."""

from __future__ import annotations

from typing import Any

from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import GlobalLiquidityEngine


class LiquidityAwareCycleExecutor(AnalyticalEngineCycleExecutor):
    """Preserve the PR27 one-engine scheduler integration contract."""

    def __init__(
        self,
        canonical_executor: Any,
        liquidity_engine: GlobalLiquidityEngine,
        store: SQLiteAnalyticalEngineStore,
    ) -> None:
        super().__init__(canonical_executor, (liquidity_engine,), store)


__all__ = ["LiquidityAwareCycleExecutor"]
