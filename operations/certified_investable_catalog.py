"""Optional complete certified instrument catalog for universal market discovery.

The built-in provider adapters remain useful bootstrap sources, but they are not a
closed investment-universe definition.  A deployment may publish every instrument it
can identify, evidence, and paper-execute through this provider-neutral contract.  The
comprehensive discovery process merges the publication before screening and applies no
asset-count or asset-class shortlist.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

SCHEMA_VERSION = "capital-intelligence-certified-investable-catalog.v1"
DEFAULT_PATH = Path("database/certified-investable-catalog.json")


class CertifiedInvestableCatalogError(RuntimeError):
    """Raised when a configured complete catalog cannot be certified."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CertifiedInvestableCatalogError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise CertifiedInvestableCatalogError(
            f"{field_name} must be ISO-8601"
        ) from error
    return _aware(parsed, field_name=field_name)


def configured_path() -> Path | None:
    value = os.getenv("CAPITAL_INTELLIGENCE_CERTIFIED_INVESTABLE_CATALOG", "").strip()
    return None if not value else Path(value).expanduser()


def load_certified_investable_catalog(
    *,
    as_of: datetime,
    path: str | Path | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Return all records in a complete point-in-time catalog publication.

    No publication is required for local fixtures or deployments that rely entirely on
    built-in provider directories.  Once a path is configured, absence, staleness,
    incompleteness, or malformed records fail closed instead of silently reverting to a
    smaller static market list.
    """

    timestamp = _aware(as_of, field_name="as_of")
    source = Path(path).expanduser() if path is not None else configured_path()
    if source is None:
        return ()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise CertifiedInvestableCatalogError(
            f"configured certified catalog is unavailable at {source}"
        ) from error
    except json.JSONDecodeError as error:
        raise CertifiedInvestableCatalogError(
            "configured certified catalog is invalid JSON"
        ) from error
    if not isinstance(payload, Mapping):
        raise CertifiedInvestableCatalogError(
            "certified catalog must be a JSON object"
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CertifiedInvestableCatalogError(
            "unsupported certified catalog schema"
        )
    if payload.get("complete") is not True:
        raise CertifiedInvestableCatalogError(
            "certified catalog does not attest complete provider coverage"
        )
    catalog_as_of = _timestamp(payload.get("as_of"), field_name="as_of")
    available_at = _timestamp(
        payload.get("available_at"), field_name="available_at"
    )
    if catalog_as_of > timestamp or available_at > timestamp:
        raise CertifiedInvestableCatalogError(
            "certified catalog contains future-known membership"
        )
    raw_records = payload.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        raise CertifiedInvestableCatalogError("catalog records must be a sequence")
    records = tuple(item for item in raw_records if isinstance(item, Mapping))
    if len(records) != len(raw_records):
        raise CertifiedInvestableCatalogError(
            "every certified catalog record must be an object"
        )
    identities: set[str] = set()
    for index, record in enumerate(records):
        identifier = str(
            record.get("instrument_identifier")
            or record.get("source_identifier")
            or ""
        ).strip()
        if not identifier:
            raise CertifiedInvestableCatalogError(
                f"records[{index}] lacks a stable instrument/source identifier"
            )
        if identifier in identities:
            raise CertifiedInvestableCatalogError(
                f"duplicate certified instrument identity: {identifier}"
            )
        identities.add(identifier)
    return records


__all__ = [
    "CertifiedInvestableCatalogError",
    "DEFAULT_PATH",
    "SCHEMA_VERSION",
    "configured_path",
    "load_certified_investable_catalog",
]
