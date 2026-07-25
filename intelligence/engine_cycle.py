"""Scheduler integration for multiple analytical engines."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from intelligence.engine_store import SQLiteAnalyticalEngineStore


class AnalyticalEngineCycleExecutor:
    """Run analytical engines beside the canonical cycle without replacing it."""

    def __init__(
        self,
        canonical_executor: Any,
        engines: Iterable[Any],
        store: SQLiteAnalyticalEngineStore,
    ) -> None:
        resolved = tuple(engines)
        if not resolved:
            raise ValueError("engines cannot be empty")
        names = [str(getattr(engine, "engine_name", "")).strip() for engine in resolved]
        if any(not name for name in names):
            raise TypeError("every analytical engine must expose engine_name")
        if len(names) != len(set(names)):
            raise ValueError("analytical engine names must be unique")
        if not isinstance(store, SQLiteAnalyticalEngineStore):
            raise TypeError("store must be a SQLiteAnalyticalEngineStore")
        self.canonical_executor = canonical_executor
        self.engines = resolved
        self.store = store

    def run(self, *, as_of):
        analytical_results = tuple(
            engine.run(as_of=as_of).result for engine in self.engines
        )
        canonical = self.canonical_executor.run(as_of=as_of)
        for result in analytical_results:
            self.store.append(result)
        return canonical


__all__ = ["AnalyticalEngineCycleExecutor"]
