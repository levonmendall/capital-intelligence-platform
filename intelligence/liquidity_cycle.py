"""Scheduler integration for the Global Liquidity engine."""

from __future__ import annotations

from typing import Any

from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import GlobalLiquidityEngine


class LiquidityAwareCycleExecutor:
    """Run liquidity beside the canonical cycle without changing its result."""

    def __init__(
        self,
        canonical_executor: Any,
        liquidity_engine: GlobalLiquidityEngine,
        store: SQLiteAnalyticalEngineStore,
    ) -> None:
        self.canonical_executor = canonical_executor
        self.liquidity_engine = liquidity_engine
        self.store = store

    def run(self, *, as_of):
        liquidity = self.liquidity_engine.run(as_of=as_of)
        canonical = self.canonical_executor.run(as_of=as_of)
        self.store.append(liquidity.result)
        return canonical


__all__ = ["LiquidityAwareCycleExecutor"]
