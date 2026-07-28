"""Configured canonical decision-information provider tests."""

from __future__ import annotations

from datetime import timedelta

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers.configured_information import ConfiguredDecisionInformationProvider
from tests.test_decision_information import AVAILABLE, CUTOFF, _record


class DatasetProvider:
    name = "CONFIGURED_INFORMATION_FIXTURE"

    def __init__(self, payload):
        self.payload = payload

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        assert query.dataset_type is ProviderDatasetType.DECISION_INFORMATION
        return ProviderDatasetSnapshot(
            query=query,
            provider=self.name,
            source_version="fixture.v1",
            observed_at=min(
                query.start_at or query.as_of - timedelta(minutes=2),
                query.as_of - timedelta(seconds=1),
            ),
            available_at=query.as_of - timedelta(seconds=1),
            retrieved_at=query.as_of,
            quality_state=DataQualityState.LIVE,
            availability_basis=AvailabilityBasis.PROVIDER_TIMESTAMP,
            payload=self.payload,
            provider_record_id="record:decision-information",
        )


def test_configured_information_adapter_returns_available_canonical_records() -> None:
    record = _record()
    provider = ConfiguredDecisionInformationProvider(
        DatasetProvider([record.to_dict()])
    )

    records = provider.records(
        start_at=AVAILABLE - timedelta(minutes=1),
        as_of=CUTOFF,
        topics=(record.topic,),
        entities=(record.entities[0],),
    )

    assert records == (record,)
    assert provider.name.endswith(":decision-information")


def test_configured_information_adapter_filters_by_time_and_entity() -> None:
    provider = ConfiguredDecisionInformationProvider(
        DatasetProvider([_record().to_dict()])
    )

    assert provider.records(
        start_at=CUTOFF,
        as_of=CUTOFF,
    ) == ()
    assert provider.records(
        start_at=AVAILABLE - timedelta(minutes=1),
        as_of=CUTOFF,
        entities=("entity:other",),
    ) == ()
