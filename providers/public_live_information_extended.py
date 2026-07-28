"""Final normalization layer for expanded public live information sources."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import PublicLiveSourceDefinition
from providers.public_live_information_runtime import (
    GovernedPublicLiveInformationProvider,
)


def _nonempty(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            normalized
            for value in values
            if (normalized := str(value).strip())
            and normalized.lower() not in {"none", "null", "nan"}
        )
    )


class ImpactfulPublicLiveInformationProvider(
    GovernedPublicLiveInformationProvider
):
    """Normalize optional dimensions before canonical record validation."""

    def _record(
        self,
        source: PublicLiveSourceDefinition,
        item: Mapping[str, Any],
        *,
        retrieved_at: datetime,
        topic: object,
        summary: object,
        event_at: object,
        published_at: object,
        source_identifier: object,
        entities: tuple[str, ...] = (),
        geographies: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> DecisionInformationRecord:
        return super()._record(
            source,
            item,
            retrieved_at=retrieved_at,
            topic=topic,
            summary=summary,
            event_at=event_at,
            published_at=published_at,
            source_identifier=source_identifier,
            entities=_nonempty(entities),
            geographies=_nonempty(geographies),
            tags=_nonempty(tags),
        )
