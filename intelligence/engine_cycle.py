"""Scheduler integration for multiple analytical engines."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.normalization import MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore


class AnalyticalEngineCycleExecutor:
    """Run analytical engines beside the canonical cycle without replacing it."""

    def __init__(
        self,
        canonical_executor: Any,
        engines: Iterable[Any],
        store: SQLiteAnalyticalEngineStore,
        *,
        normalizer: MultiEngineNormalizer | None = None,
        normalization_store: SQLiteNormalizationStore | None = None,
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
        if (normalizer is None) != (normalization_store is None):
            raise ValueError(
                "normalizer and normalization_store must be provided together"
            )
        if normalizer is not None and not isinstance(
            normalizer,
            MultiEngineNormalizer,
        ):
            raise TypeError("normalizer must be a MultiEngineNormalizer")
        if normalization_store is not None and not isinstance(
            normalization_store,
            SQLiteNormalizationStore,
        ):
            raise TypeError(
                "normalization_store must be a SQLiteNormalizationStore"
            )
        self.canonical_executor = canonical_executor
        self.engines = resolved
        self.store = store
        self.normalizer = normalizer
        self.normalization_store = normalization_store

    def run(self, *, as_of):
        analytical_results = tuple(
            engine.run(as_of=as_of).result for engine in self.engines
        )
        canonical = self.canonical_executor.run(as_of=as_of)
        for result in analytical_results:
            self.store.append(result)
        if self.normalizer is not None and self.normalization_store is not None:
            bundle = self.normalizer.normalize(analytical_results, as_of=as_of)
            self.normalization_store.append(bundle)
        return canonical


__all__ = ["AnalyticalEngineCycleExecutor"]
