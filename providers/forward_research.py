"""Configured provider adapter for certified forward-research evidence.

The adapter activates only dataset types explicitly bound in a configured provider
file.  Missing bindings remain unavailable and do not become synthetic evidence.
A configured binding that is present but fails retrieval/validation raises, so a
claimed certified feed cannot silently degrade into the market proxy.
"""
from __future__ import annotations

import os
from pathlib import Path

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from intelligence.forward_research import (
    ExpectationsIntelligenceEngine,
    ForwardResearchEvidence,
    GovernedNowcastingEngine,
    PositioningIntelligenceEngine,
    expectation_observations_from_snapshot,
    nowcast_observations_from_snapshot,
    positioning_observations_from_snapshot,
)
from providers.configured_dataset import ConfiguredDatasetProvider


_FORWARD_TYPES = frozenset({
    ProviderDatasetType.EXPECTATIONS,
    ProviderDatasetType.EVENT_EXPECTATIONS,
    ProviderDatasetType.POSITIONING,
    ProviderDatasetType.DERIVATIVE_POSITIONING,
    ProviderDatasetType.LEADING_INDICATORS,
})


class ConfiguredForwardResearchProvider:
    """Materialize certified forward evidence for one governed candidate."""

    def __init__(self, provider: ConfiguredDatasetProvider) -> None:
        if not isinstance(provider, ConfiguredDatasetProvider):
            raise TypeError("provider must be ConfiguredDatasetProvider")
        self.provider = provider
        self.bound_types = frozenset(
            binding.dataset_type
            for binding in provider.settings.bindings
            if binding.dataset_type in _FORWARD_TYPES
        )
        if not self.bound_types:
            raise ValueError("configured provider has no forward-research bindings")

    @property
    def name(self) -> str:
        return f"{self.provider.name}:forward-research"

    def _snapshot(self, dataset_type: ProviderDatasetType, *, symbol: str, as_of):
        if dataset_type not in self.bound_types:
            return None
        return self.provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=dataset_type,
                provider_symbol=str(symbol).upper(),
                as_of=as_of,
                limit=1_000,
            )
        )

    def fetch(self, candidate) -> ForwardResearchEvidence | None:
        symbol = candidate.instrument.symbol
        as_of = candidate.as_of
        expectation_observations = []
        for dataset_type in (
            ProviderDatasetType.EXPECTATIONS,
            ProviderDatasetType.EVENT_EXPECTATIONS,
        ):
            snapshot = self._snapshot(dataset_type, symbol=symbol, as_of=as_of)
            if snapshot is not None:
                expectation_observations.extend(
                    expectation_observations_from_snapshot(snapshot)
                )
        positioning_observations = []
        for dataset_type in (
            ProviderDatasetType.POSITIONING,
            ProviderDatasetType.DERIVATIVE_POSITIONING,
        ):
            snapshot = self._snapshot(dataset_type, symbol=symbol, as_of=as_of)
            if snapshot is not None:
                positioning_observations.extend(
                    positioning_observations_from_snapshot(snapshot)
                )
        leading_snapshot = self._snapshot(
            ProviderDatasetType.LEADING_INDICATORS,
            symbol=symbol,
            as_of=as_of,
        )
        nowcast_observations = (
            ()
            if leading_snapshot is None
            else nowcast_observations_from_snapshot(leading_snapshot)
        )
        expectations = (
            None
            if not expectation_observations
            else ExpectationsIntelligenceEngine().analyze(
                tuple(expectation_observations)
            )
        )
        positioning = (
            None
            if not positioning_observations
            else PositioningIntelligenceEngine().analyze(
                tuple(positioning_observations)
            )
        )
        grouped = {}
        for observation in nowcast_observations:
            grouped.setdefault(observation.target, []).append(observation)
        nowcasts = tuple(
            GovernedNowcastingEngine().estimate(tuple(observations))
            for _target, observations in sorted(
                grouped.items(), key=lambda item: item[0].value
            )
        )
        if expectations is None and positioning is None and not nowcasts:
            return None
        return ForwardResearchEvidence(
            expectations=expectations,
            positioning=positioning,
            nowcasts=nowcasts,
        )


def build_configured_forward_research_provider(
    path: str | Path | None = None,
) -> ConfiguredForwardResearchProvider | None:
    configured_path = str(
        path
        or os.getenv("CAPITAL_INTELLIGENCE_FORWARD_RESEARCH_DATASET_BINDING", "")
    ).strip()
    if not configured_path:
        return None
    return ConfiguredForwardResearchProvider(
        ConfiguredDatasetProvider.from_path(configured_path)
    )


__all__ = [
    "ConfiguredForwardResearchProvider",
    "build_configured_forward_research_provider",
]
