"""Canonical pipeline adapters for configuration-driven governed datasets.

These adapters keep vendor response details inside ``ConfiguredDatasetProvider``
while exposing the exact repository protocols used by security-master ingestion
and complete-universe screening.  Provider payloads must already conform to the
canonical schemas; the adapters validate identity, timestamps, and lineage and
fail closed rather than guessing field meanings.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Mapping

from data.provider_dataset import (
    ProviderDatasetProvider,
    ProviderDatasetQuery,
    ProviderDatasetType,
)
from data.security_master import (
    PointInTimeSecurityMasterSnapshot,
    SecurityMasterMarketMetrics,
    Version1UniverseConstituent,
)
from data.security_master_ingestion import (
    SecurityMasterCatalogDelivery,
    SecurityMasterIngestionQuery,
    SecurityMasterProviderError,
)
from data.security_master_store import deserialize_security_master_catalog
from providers.configured_dataset import ConfiguredDatasetProvider
from screening.orchestration import (
    CandidateScreeningDecision,
    FullUniverseScreeningError,
    candidate_from_payload,
)


class ConfiguredPipelineAdapterError(RuntimeError):
    """Raised when a configured dataset cannot satisfy a canonical protocol."""


def _dataset_provider(
    path: str | Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> ConfiguredDatasetProvider:
    return ConfiguredDatasetProvider.from_path(path, environment=environment)


class ConfiguredSecurityMasterProvider:
    """Adapt canonical ``security-master-catalog.v1`` payloads for ingestion."""

    def __init__(self, provider: ProviderDatasetProvider) -> None:
        if not isinstance(provider, ProviderDatasetProvider):
            raise TypeError("provider must implement ProviderDatasetProvider")
        self.provider = provider

    @property
    def name(self) -> str:
        return f"{self.provider.name}:security-master"

    def fetch_security_master_delivery(
        self,
        query: SecurityMasterIngestionQuery,
    ) -> SecurityMasterCatalogDelivery:
        if not isinstance(query, SecurityMasterIngestionQuery):
            raise TypeError("query must be SecurityMasterIngestionQuery")
        try:
            snapshot = self.provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.SECURITY_MASTER,
                    provider_symbol="ALL",
                    as_of=query.knowledge_cutoff,
                    start_at=query.as_of,
                    end_at=query.as_of,
                    limit=1_000_000,
                )
            )
            if not isinstance(snapshot.payload, dict):
                raise ConfiguredPipelineAdapterError(
                    "security-master dataset must contain one canonical catalog object"
                )
            catalog = deserialize_security_master_catalog(snapshot.payload)
            # Building the point-in-time view proves temporal availability and
            # authoritative coverage before the ingestion service persists it.
            catalog.snapshot(
                as_of=query.as_of,
                knowledge_cutoff=query.knowledge_cutoff,
                require_authoritative=True,
            )
            return SecurityMasterCatalogDelivery(
                catalog=catalog,
                observed_at=snapshot.observed_at,
                retrieved_at=snapshot.retrieved_at,
                request_identifier=(
                    snapshot.provider_record_id
                    or f"{query.identifier}:{snapshot.content_hash[:20]}"
                ),
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            raise SecurityMasterProviderError(
                f"configured security-master delivery is invalid: {error}"
            ) from error


class ConfiguredUniverseMetricsProvider:
    """Adapt canonical point-in-time liquidity/coverage metrics for screening."""

    def __init__(self, provider: ProviderDatasetProvider) -> None:
        if not isinstance(provider, ProviderDatasetProvider):
            raise TypeError("provider must implement ProviderDatasetProvider")
        self.provider = provider

    @property
    def name(self) -> str:
        return f"{self.provider.name}:universe-metrics"

    def fetch_metrics(
        self,
        snapshot: PointInTimeSecurityMasterSnapshot,
    ) -> tuple[SecurityMasterMarketMetrics, ...]:
        if not isinstance(snapshot, PointInTimeSecurityMasterSnapshot):
            raise TypeError("snapshot must be PointInTimeSecurityMasterSnapshot")
        try:
            result = self.provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.QUOTES_LIQUIDITY,
                    provider_symbol="ALL",
                    as_of=snapshot.knowledge_cutoff,
                    start_at=snapshot.as_of,
                    end_at=snapshot.as_of,
                    limit=1_000_000,
                )
            )
            if not isinstance(result.payload, list):
                raise ConfiguredPipelineAdapterError(
                    "universe metrics dataset must contain an array"
                )
            metrics = tuple(_metric(item) for item in result.payload)
            identifiers = tuple(item.instrument_identifier for item in metrics)
            if len(identifiers) != len(set(identifiers)):
                raise ConfiguredPipelineAdapterError(
                    "universe metrics contain duplicate instruments"
                )
            for item in metrics:
                if item.observed_at > snapshot.as_of:
                    raise ConfiguredPipelineAdapterError(
                        f"metric {item.identifier} was observed after universe as_of"
                    )
                if item.available_at > snapshot.knowledge_cutoff:
                    raise ConfiguredPipelineAdapterError(
                        f"metric {item.identifier} was unavailable at knowledge cutoff"
                    )
            return metrics
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            if isinstance(error, FullUniverseScreeningError):
                raise
            raise FullUniverseScreeningError(
                f"configured universe metrics are invalid: {error}"
            ) from error


class ConfiguredCandidateScreeningProvider:
    """Adapt canonical ``candidate-screening-decision.v1`` model output."""

    def __init__(self, provider: ProviderDatasetProvider) -> None:
        if not isinstance(provider, ProviderDatasetProvider):
            raise TypeError("provider must implement ProviderDatasetProvider")
        self.provider = provider

    @property
    def name(self) -> str:
        return f"{self.provider.name}:candidate-screening"

    def screen(
        self,
        constituent: Version1UniverseConstituent,
        *,
        as_of: datetime,
        opportunity_cost_return: float,
    ) -> CandidateScreeningDecision:
        if not isinstance(constituent, Version1UniverseConstituent):
            raise TypeError("constituent must be Version1UniverseConstituent")
        try:
            result = self.provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.CANDIDATE_SCREENING,
                    provider_symbol=constituent.instrument.symbol,
                    as_of=as_of,
                    limit=1,
                )
            )
            if not isinstance(result.payload, dict):
                raise ConfiguredPipelineAdapterError(
                    "candidate screening dataset must contain an object"
                )
            payload = result.payload
            if payload.get("schema_version") != "candidate-screening-decision.v1":
                raise ConfiguredPipelineAdapterError(
                    "unsupported candidate screening decision schema"
                )
            candidate_payload = payload.get("candidate")
            reasons = tuple(str(item) for item in payload.get("reasons", ()))
            if candidate_payload is None:
                return CandidateScreeningDecision(candidate=None, reasons=reasons)
            if not isinstance(candidate_payload, dict):
                raise ConfiguredPipelineAdapterError(
                    "candidate must be an object or null"
                )
            candidate = candidate_from_payload(candidate_payload)
            instrument = constituent.instrument
            if candidate.instrument.instrument_id != instrument.instrument_id:
                raise ConfiguredPipelineAdapterError(
                    "candidate instrument identity does not match constituent"
                )
            if candidate.instrument.symbol != instrument.symbol:
                raise ConfiguredPipelineAdapterError(
                    "candidate symbol does not match constituent"
                )
            if candidate.as_of != as_of:
                raise ConfiguredPipelineAdapterError(
                    "candidate as_of does not match screening timestamp"
                )
            if abs(candidate.opportunity_cost_return - opportunity_cost_return) > 1e-9:
                raise ConfiguredPipelineAdapterError(
                    "candidate opportunity cost does not match screening context"
                )
            return CandidateScreeningDecision(candidate=candidate, reasons=())
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            raise FullUniverseScreeningError(
                f"configured candidate screening output is invalid: {error}"
            ) from error


def _metric(payload: object) -> SecurityMasterMarketMetrics:
    if not isinstance(payload, dict):
        raise TypeError("each universe metric must be an object")
    return SecurityMasterMarketMetrics(
        identifier=str(payload["identifier"]),
        instrument_identifier=str(payload["instrument_identifier"]),
        observed_at=datetime.fromisoformat(str(payload["observed_at"])),
        available_at=datetime.fromisoformat(str(payload["available_at"])),
        average_daily_dollar_volume=float(
            payload["average_daily_dollar_volume"]
        ),
        analytical_coverage=float(payload["analytical_coverage"]),
        is_us_treasury=bool(payload.get("is_us_treasury", False)),
        effective_duration_years=(
            None
            if payload.get("effective_duration_years") is None
            else float(payload["effective_duration_years"])
        ),
    )


def build_configured_security_master_provider(
) -> ConfiguredSecurityMasterProvider:
    path = os.getenv("CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATASET_BINDING")
    if not path:
        raise ConfiguredPipelineAdapterError(
            "CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATASET_BINDING is required"
        )
    return ConfiguredSecurityMasterProvider(_dataset_provider(path))


def build_configured_universe_metrics_provider(
) -> ConfiguredUniverseMetricsProvider:
    path = os.getenv("CAPITAL_INTELLIGENCE_UNIVERSE_METRICS_DATASET_BINDING")
    if not path:
        raise ConfiguredPipelineAdapterError(
            "CAPITAL_INTELLIGENCE_UNIVERSE_METRICS_DATASET_BINDING is required"
        )
    return ConfiguredUniverseMetricsProvider(_dataset_provider(path))


def build_configured_candidate_screening_provider(
) -> ConfiguredCandidateScreeningProvider:
    path = os.getenv("CAPITAL_INTELLIGENCE_CANDIDATE_SCREENING_DATASET_BINDING")
    if not path:
        raise ConfiguredPipelineAdapterError(
            "CAPITAL_INTELLIGENCE_CANDIDATE_SCREENING_DATASET_BINDING is required"
        )
    return ConfiguredCandidateScreeningProvider(_dataset_provider(path))


__all__ = [
    "ConfiguredCandidateScreeningProvider",
    "ConfiguredPipelineAdapterError",
    "ConfiguredSecurityMasterProvider",
    "ConfiguredUniverseMetricsProvider",
    "build_configured_candidate_screening_provider",
    "build_configured_security_master_provider",
    "build_configured_universe_metrics_provider",
]
