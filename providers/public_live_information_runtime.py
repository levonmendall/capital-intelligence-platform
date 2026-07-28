"""Runtime safeguards for public live information collection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import (
    PublicLiveInformationProvider,
    PublicLiveSourceDefinition,
    _parse_timestamp,
)


class GovernedPublicLiveInformationProvider(PublicLiveInformationProvider):
    """Preserve future scheduled-event time without violating the v1 record contract.

    The canonical v1 contract currently requires publication time to be at or after
    event time. Official sources such as the National Weather Service may publish a
    watch before its onset. Until a versioned record-contract upgrade is introduced,
    this runtime adapter records publication time as the event boundary and retains
    the announced future onset in a deterministic tag and the raw-record hash.
    """

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
        published = _parse_timestamp(published_at, fallback=retrieved_at)
        event = _parse_timestamp(event_at, fallback=published)
        normalized_tags = tags
        normalized_event: object = event
        if event > published:
            normalized_event = published
            normalized_tags = tags + (
                "scheduled-event",
                f"scheduled-event-at:{event.isoformat()}",
            )
        return super()._record(
            source,
            item,
            retrieved_at=retrieved_at,
            topic=topic,
            summary=summary,
            event_at=normalized_event,
            published_at=published,
            source_identifier=source_identifier,
            entities=entities,
            geographies=geographies,
            tags=normalized_tags,
        )
