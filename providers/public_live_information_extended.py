"""Final normalization layer for expanded public live information sources."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import (
    PublicLiveSourceDefinition,
    _hash_payload,
)
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
    """Normalize optional dimensions and official legacy formats."""

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

    def _parse_ofac_csv(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        text = response.text.lstrip("\ufeff")
        first_row = next(csv.reader(io.StringIO(text)), [])
        normalized_headers = {str(item).strip().lower() for item in first_row}
        expected = {"ent_num", "sdn_name", "sdn_type", "program"}
        if expected & normalized_headers:
            reader = csv.DictReader(io.StringIO(text))
        else:
            reader = csv.DictReader(
                io.StringIO(text),
                fieldnames=(
                    "ent_num",
                    "sdn_name",
                    "sdn_type",
                    "program",
                    "title",
                    "call_sign",
                    "vess_type",
                    "tonnage",
                    "grt",
                    "vess_flag",
                    "vess_owner",
                    "remarks",
                ),
            )
        output: list[DecisionInformationRecord] = []
        for raw in reader:
            item = {
                str(key or "").strip().lower(): value
                for key, value in raw.items()
            }
            name = (
                item.get("sdn_name")
                or item.get("name")
                or item.get("primary name")
            )
            if not name:
                continue
            entity_type = item.get("sdn_type") or item.get("type") or "target"
            program = item.get("program") or item.get("programs") or "unspecified"
            remarks = item.get("remarks") or item.get("comments") or ""
            identifier = (
                item.get("ent_num")
                or item.get("entity number")
                or _hash_payload(item)
            )
            flag = item.get("vess_flag") or item.get("country") or ""
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"OFAC sanctions listing: {name}",
                    summary=(
                        f"Type {entity_type}; program {program}. "
                        f"{remarks}"
                    ),
                    event_at=retrieved_at,
                    published_at=retrieved_at,
                    source_identifier=identifier,
                    entities=(str(name),),
                    geographies=((str(flag),) if flag else ()),
                    tags=(str(entity_type), str(program), "sanctions-list"),
                )
            )
        return output
