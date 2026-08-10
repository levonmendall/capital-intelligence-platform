"""Configured and public adapters for certified forward-research evidence.

Explicit configured dataset bindings remain preferred.  When none is configured, the
provider may expose a conservative matched subset of already-certified public
positioning observations (currently CFTC managed-money evidence).  Missing bindings
or unmatched public evidence remain unavailable and do not become synthetic neutral
signals.  Neither path has investment authority.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from intelligence.forward_research import (
    ExpectationsIntelligenceEngine,
    ForwardResearchEvidence,
    GovernedNowcastingEngine,
    PositioningIntelligenceEngine,
    ValueOfWaitingEngine,
    ValueOfWaitingInputs,
    expectation_observations_from_snapshot,
    nowcast_observations_from_snapshot,
    positioning_observations_from_snapshot,
)
from providers.configured_dataset import ConfiguredDatasetProvider
from providers.public_forward_research import (
    PublicForwardResearchProvider,
    build_public_forward_research_provider,
)


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

    @staticmethod
    def _event_components(snapshot):
        """Return expectation rows plus one explicit value-of-waiting contract.

        EVENT_EXPECTATIONS supports the legacy list payload and the governed object
        form ``{"expectations": [...], "value_of_waiting": {...}}``.  Timing inputs
        are never inferred from price or consensus fields.
        """

        payload = snapshot.payload
        if not isinstance(payload, Mapping):
            return snapshot, None
        if "expectations" not in payload and "value_of_waiting" not in payload:
            return snapshot, None
        expectation_rows = payload.get("expectations", [])
        if not isinstance(expectation_rows, list):
            raise TypeError("event expectations must be an array")
        raw_wait = payload.get("value_of_waiting")
        if raw_wait is not None and not isinstance(raw_wait, Mapping):
            raise TypeError("value_of_waiting must be an object")
        return replace(snapshot, payload=expectation_rows), raw_wait

    def fetch(self, candidate) -> ForwardResearchEvidence | None:
        symbol = candidate.instrument.symbol
        as_of = candidate.as_of
        expectation_observations = []
        raw_wait = None
        for dataset_type in (
            ProviderDatasetType.EXPECTATIONS,
            ProviderDatasetType.EVENT_EXPECTATIONS,
        ):
            snapshot = self._snapshot(dataset_type, symbol=symbol, as_of=as_of)
            if snapshot is None:
                continue
            if dataset_type is ProviderDatasetType.EVENT_EXPECTATIONS:
                expectation_snapshot, candidate_wait = self._event_components(snapshot)
                if candidate_wait is not None:
                    if raw_wait is not None:
                        raise ValueError("multiple value-of-waiting contracts are ambiguous")
                    raw_wait = (snapshot, candidate_wait)
                snapshot = expectation_snapshot
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
        value_of_waiting = None
        if raw_wait is not None:
            snapshot, row = raw_wait
            evidence_ids = [f"provider-dataset:{snapshot.provider}:{snapshot.content_hash}"]
            raw_ids = row.get("evidence_identifiers", [])
            if not isinstance(raw_ids, list):
                raise TypeError("value-of-waiting evidence_identifiers must be an array")
            evidence_ids.extend(str(item).strip() for item in raw_ids if str(item).strip())
            value_of_waiting = ValueOfWaitingEngine().assess(
                ValueOfWaitingInputs(
                    as_of=as_of,
                    invest_now_expected_return=float(row["invest_now_expected_return"]),
                    downside_if_unresolved=float(row["downside_if_unresolved"]),
                    probability_uncertainty_resolves=float(row["probability_uncertainty_resolves"]),
                    expected_upside_lost_by_waiting=float(row["expected_upside_lost_by_waiting"]),
                    expected_post_event_entry_drag=float(row["expected_post_event_entry_drag"]),
                    transaction_cost_return=float(row["transaction_cost_return"]),
                    alternative_return_while_waiting=float(row["alternative_return_while_waiting"]),
                    thesis_decay_return=float(row["thesis_decay_return"]),
                    evidence_identifiers=tuple(dict.fromkeys(evidence_ids)),
                )
            )
        if (
            expectations is None
            and positioning is None
            and not nowcasts
            and value_of_waiting is None
        ):
            return None
        return ForwardResearchEvidence(
            expectations=expectations,
            positioning=positioning,
            nowcasts=nowcasts,
            value_of_waiting=value_of_waiting,
        )


def build_configured_forward_research_provider(
    path: str | Path | None = None,
) -> ConfiguredForwardResearchProvider | PublicForwardResearchProvider | None:
    """Prefer an explicit licensed/configured binding, else strict public research."""

    configured_path = str(
        path
        or os.getenv("CAPITAL_INTELLIGENCE_FORWARD_RESEARCH_DATASET_BINDING", "")
    ).strip()
    if configured_path:
        return ConfiguredForwardResearchProvider(
            ConfiguredDatasetProvider.from_path(configured_path)
        )
    return build_public_forward_research_provider()


__all__ = [
    "ConfiguredForwardResearchProvider",
    "build_configured_forward_research_provider",
]
