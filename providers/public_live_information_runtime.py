"""Runtime safeguards for public live information collection."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import (
    PublicLiveInformationError,
    PublicLiveInformationProvider,
    PublicLiveSourceDefinition,
    _parse_timestamp,
)


class GovernedPublicLiveInformationProvider(PublicLiveInformationProvider):
    """Apply fail-closed parsing and scheduled-event safeguards.

    The canonical v1 record currently requires publication time to be at or after
    event time. Official sources may announce a scheduled event before it begins.
    Until a versioned record-contract upgrade is introduced, publication time is
    used as the canonical event boundary and the scheduled onset is retained in a
    deterministic tag and the raw-record hash.
    """

    def _collect_source(
        self,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ):
        try:
            return super()._collect_source(source, retrieved_at)
        except (
            ET.ParseError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as error:
            raise PublicLiveInformationError(
                f"{source.identifier} returned an invalid payload: {error}"
            ) from error

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
        normalized_raw_event = event_at
        if isinstance(event_at, str) and len(event_at.strip()) == 4 and event_at.strip().isdigit():
            normalized_raw_event = f"{event_at.strip()}-01-01"
        published = _parse_timestamp(published_at, fallback=retrieved_at)
        normalized_tags = tags
        if published > retrieved_at:
            normalized_tags = normalized_tags + (
                "future-publication-normalized",
                f"reported-publication-at:{published.isoformat()}",
            )
            published = retrieved_at
        event = _parse_timestamp(normalized_raw_event, fallback=published)
        normalized_event: object = event
        if event > published:
            normalized_event = published
            normalized_tags = normalized_tags + (
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
