"""Build a bounded identity-enrichment queue from persisted public catalogs.

This module never activates a security master and never authorizes screening.
It summarizes discovery breadth and emits a small queue of unresolved ISINs for
later OpenFIGI/GLEIF enrichment by background maintenance.  The canonical
certified security-master and capability gates remain the only authority for
investment eligibility.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass(frozen=True, slots=True)
class PublicCatalogReconciliationReport:
    evaluated_at: datetime
    source_count: int
    page_count: int
    instrument_count: int
    isin_count: int
    figi_count: int
    country_counts: Mapping[str, int]
    venue_counts: Mapping[str, int]
    openfigi_queue: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "global-public-catalog-reconciliation.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "source_count": self.source_count,
            "page_count": self.page_count,
            "instrument_count": self.instrument_count,
            "isin_count": self.isin_count,
            "figi_count": self.figi_count,
            "country_counts": dict(self.country_counts),
            "venue_counts": dict(self.venue_counts),
            "openfigi_queue": [dict(item) for item in self.openfigi_queue],
            "screening_authority": False,
            "decision_evidence_authority": False,
            "investment_authority": False,
            "execution_authority": False,
            "activation_performed": False,
            "real_money_authorized": False,
        }


def reconcile_global_public_catalogs(
    *,
    values: Mapping[str, str] | None = None,
    queue_limit: int = 100,
    clock=_utc_now,
) -> PublicCatalogReconciliationReport:
    """Summarize persisted catalog pages and queue unresolved ISIN mappings."""

    if not 1 <= queue_limit <= 1000:
        raise ValueError("queue_limit must be between 1 and 1000")
    resolved = dict(os.environ if values is None else values)
    root = (
        Path(resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
        / "global_public_catalogs"
    )
    sources: set[str] = set()
    page_count = 0
    instrument_count = 0
    isin_count = 0
    figi_count = 0
    country_counts: dict[str, int] = {}
    venue_counts: dict[str, int] = {}
    queue: list[Mapping[str, str]] = []
    queued_isins: set[str] = set()

    for path in sorted(root.glob("*/pages/*.json")):
        payload = _read(path)
        if payload is None:
            continue
        records = payload.get("records", [])
        if not isinstance(records, list):
            continue
        page_count += 1
        source_identifier = str(payload.get("source_identifier", "")).strip()
        if source_identifier:
            sources.add(source_identifier)
        for raw in records:
            if not isinstance(raw, Mapping):
                continue
            instrument_count += 1
            isin = str(raw.get("isin", "")).strip().upper()
            figi = str(raw.get("figi", "")).strip().upper()
            country = str(raw.get("country_code", "ZZ")).strip().upper() or "ZZ"
            venue = str(raw.get("venue", "UNKNOWN")).strip().upper() or "UNKNOWN"
            country_counts[country] = country_counts.get(country, 0) + 1
            venue_counts[venue] = venue_counts.get(venue, 0) + 1
            if isin:
                isin_count += 1
            if figi:
                figi_count += 1
            if (
                isin
                and not figi
                and isin not in queued_isins
                and len(queue) < queue_limit
            ):
                queued_isins.add(isin)
                queue.append(
                    {
                        "id_type": "ID_ISIN",
                        "id_value": isin,
                        "source_identifier": source_identifier,
                        "venue": venue,
                        "country_code": country,
                    }
                )

    report = PublicCatalogReconciliationReport(
        evaluated_at=clock(),
        source_count=len(sources),
        page_count=page_count,
        instrument_count=instrument_count,
        isin_count=isin_count,
        figi_count=figi_count,
        country_counts=dict(sorted(country_counts.items())),
        venue_counts=dict(sorted(venue_counts.items())),
        openfigi_queue=tuple(queue),
    )
    _write(root / "reconciliation_latest.json", report.to_dict())
    return report


__all__ = [
    "PublicCatalogReconciliationReport",
    "reconcile_global_public_catalogs",
]
