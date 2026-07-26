"""Scheduler integration for multiple analytical engines."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.governance import MultiEngineGovernor
from intelligence.governance_store import SQLiteGovernanceStore
from intelligence.normalization import MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore
from intelligence.synthesis_store import SQLiteSynthesisStore
from intelligence.synthesis_weights import MultiEngineSynthesizer


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
        synthesizer: MultiEngineSynthesizer | None = None,
        synthesis_store: SQLiteSynthesisStore | None = None,
        governor: MultiEngineGovernor | None = None,
        governance_store: SQLiteGovernanceStore | None = None,
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
        if (synthesizer is None) != (synthesis_store is None):
            raise ValueError(
                "synthesizer and synthesis_store must be provided together"
            )
        if (governor is None) != (governance_store is None):
            raise ValueError(
                "governor and governance_store must be provided together"
            )
        if synthesizer is not None and normalizer is None:
            raise ValueError("weighted synthesis requires normalization")
        if governor is not None and synthesizer is None:
            raise ValueError("governance requires weighted synthesis")
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
        if synthesizer is not None and not isinstance(
            synthesizer,
            MultiEngineSynthesizer,
        ):
            raise TypeError("synthesizer must be a MultiEngineSynthesizer")
        if synthesis_store is not None and not isinstance(
            synthesis_store,
            SQLiteSynthesisStore,
        ):
            raise TypeError("synthesis_store must be a SQLiteSynthesisStore")
        if governor is not None and not isinstance(governor, MultiEngineGovernor):
            raise TypeError("governor must be a MultiEngineGovernor")
        if governance_store is not None and not isinstance(
            governance_store,
            SQLiteGovernanceStore,
        ):
            raise TypeError("governance_store must be a SQLiteGovernanceStore")
        self.canonical_executor = canonical_executor
        self.engines = resolved
        self.store = store
        self.normalizer = normalizer
        self.normalization_store = normalization_store
        self.synthesizer = synthesizer
        self.synthesis_store = synthesis_store
        self.governor = governor
        self.governance_store = governance_store

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
            if self.synthesizer is not None and self.synthesis_store is not None:
                synthesis = self.synthesizer.synthesize(bundle)
                self.synthesis_store.append_policy(self.synthesizer.policy)
                self.synthesis_store.append(synthesis)
                if self.governor is not None and self.governance_store is not None:
                    governance = self.governor.evaluate(bundle, synthesis)
                    self.governance_store.append_policy(self.governor.policy)
                    self.governance_store.append(governance)
        return canonical


__all__ = ["AnalyticalEngineCycleExecutor"]
