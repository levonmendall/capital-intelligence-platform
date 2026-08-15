"""Continuously acquire public global instrument catalogs outside the CIO path.

Each maintenance pass is bounded. Page results are written atomically, projected
into the canonical append-only security-master store as non-authoritative
discovery catalogs, and checkpointed for the next pass. No public catalog in
this module can activate itself for screening.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from data.security_master_store import SQLiteSecurityMasterStore
from providers.public_security_catalog import (
    NormalizedPublicInstrument,
    PublicCatalogSourceDefinition,
    PublicSecurityCatalogProvider,
    security_master_delivery_from_public_records,
)

_DEFAULT_CONFIG = Path("config/global_public_security_catalogs.json")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _record_payload(item: NormalizedPublicInstrument) -> dict[str, Any]:
    payload = asdict(item)
    payload["asset_class"] = item.asset_class.value
    payload["instrument_type"] = item.instrument_type.value
    return payload


@dataclass(frozen=True, slots=True)
class PublicCatalogMaintenanceResult:
    source_identifier: str
    state: str
    record_count: int
    next_cursor: str | None
    complete: bool
    catalog_identifier: str | None
    content_hash: str | None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GlobalPublicCatalogMaintenanceReport:
    evaluated_at: datetime
    results: tuple[PublicCatalogMaintenanceResult, ...]

    @property
    def succeeded_count(self) -> int:
        return sum(item.state in {"stored", "fresh"} for item in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "global-public-catalog-maintenance.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "source_count": len(self.results),
            "succeeded_count": self.succeeded_count,
            "results": [item.to_dict() for item in self.results],
            "readiness_authority": False,
            "investment_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }


def _load_config(
    path: Path,
    *,
    values: Mapping[str, str],
) -> tuple[tuple[PublicCatalogSourceDefinition, int], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "global-public-security-catalogs.v1":
        raise ValueError("unsupported global public security catalog schema")
    output: list[tuple[PublicCatalogSourceDefinition, int]] = []
    for raw in payload.get("sources", []):
        if not isinstance(raw, Mapping) or not bool(raw.get("enabled", True)):
            continue
        endpoint = str(raw.get("endpoint", "")).strip()
        endpoint_env = str(raw.get("endpoint_environment_variable", "")).strip()
        configured_endpoint = str(values.get(endpoint_env, "")).strip() if endpoint_env else ""
        if configured_endpoint:
            endpoint = configured_endpoint
        elif bool(raw.get("requires_endpoint_configuration", False)):
            # Dynamic regulator/exchange download links are configured at runtime;
            # never scrape an HTML landing page as though it were reference data.
            continue
        source = PublicCatalogSourceDefinition(
            identifier=str(raw["identifier"]),
            source_name=str(raw["source_name"]),
            endpoint=endpoint,
            parser=str(raw["parser"]),
            venue=str(raw.get("venue", "UNKNOWN")),
            country_code=str(raw.get("country_code", "ZZ")),
            page_size=int(raw.get("page_size", 500)),
            maximum_pages_per_pass=int(raw.get("maximum_pages_per_pass", 1)),
            licensed_for_internal_analysis=bool(
                raw.get("licensed_for_internal_analysis", True)
            ),
            point_in_time=bool(raw.get("point_in_time", False)),
            historical_identifiers=bool(raw.get("historical_identifiers", False)),
            listing_history=bool(raw.get("listing_history", False)),
            delistings=bool(raw.get("delistings", False)),
            corporate_actions=bool(raw.get("corporate_actions", False)),
            provenance_complete=bool(raw.get("provenance_complete", True)),
            service_level_defined=bool(raw.get("service_level_defined", False)),
        )
        output.append((source, int(raw.get("minimum_refresh_seconds", 86400))))
    return tuple(output)


def maintain_global_public_catalogs(
    *,
    values: Mapping[str, str] | None = None,
    config_path: str | Path = _DEFAULT_CONFIG,
    clock=_utc_now,
    provider_factory=PublicSecurityCatalogProvider,
) -> GlobalPublicCatalogMaintenanceReport:
    """Acquire at most one bounded page per configured source and persist it."""

    resolved = dict(os.environ if values is None else values)
    evaluated_at = clock()
    state_root = Path(resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    root = state_root / "global_public_catalogs"
    store = SQLiteSecurityMasterStore(
        root / "public_discovery_security_master.sqlite3"
    )
    results: list[PublicCatalogMaintenanceResult] = []

    for source, minimum_refresh_seconds in _load_config(
        Path(config_path), values=resolved
    ):
        source_root = root / source.identifier
        checkpoint_path = source_root / "checkpoint.json"
        checkpoint: dict[str, Any] = {}
        if checkpoint_path.exists():
            try:
                decoded = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint = decoded if isinstance(decoded, dict) else {}
            except (OSError, json.JSONDecodeError):
                checkpoint = {}

        completed_at_raw = str(checkpoint.get("completed_at", "")).strip()
        if completed_at_raw:
            try:
                completed_at = datetime.fromisoformat(completed_at_raw)
            except ValueError:
                completed_at = None
            if completed_at is not None:
                age = (evaluated_at - completed_at).total_seconds()
                if age < minimum_refresh_seconds:
                    results.append(
                        PublicCatalogMaintenanceResult(
                            source_identifier=source.identifier,
                            state="fresh",
                            record_count=0,
                            next_cursor=None,
                            complete=True,
                            catalog_identifier=(
                                str(checkpoint.get("catalog_identifier") or "") or None
                            ),
                            content_hash=(
                                str(checkpoint.get("content_hash") or "") or None
                            ),
                            detail=f"refresh deferred; age_seconds={max(0, int(age))}",
                        )
                    )
                    continue
                checkpoint = {}

        cursor = str(checkpoint.get("next_cursor", "")).strip() or None
        try:
            page = provider_factory(source).fetch_page(cursor=cursor)
            if not page.records:
                raise ValueError(
                    "public catalog page contained no normalized instruments"
                )
            # Content hash makes every immutable page independently addressable. It
            # prevents a multi-page FIRDS traversal from colliding with an earlier
            # page while retaining append-only history across refreshes.
            delivery = security_master_delivery_from_public_records(
                source,
                page.records,
                observed_at=page.retrieved_at,
                retrieved_at=page.retrieved_at,
                complete_source_snapshot=page.complete and cursor in {None, "0"},
                catalog_fingerprint=page.content_hash,
            )
            event = store.append(delivery.catalog, recorded_at=page.retrieved_at)
            page_path = source_root / "pages" / f"{page.content_hash}.json"
            _atomic_json(
                page_path,
                {
                    "schema_version": "global-public-catalog-page.v1",
                    "source_identifier": source.identifier,
                    "retrieved_at": page.retrieved_at.isoformat(),
                    "content_hash": page.content_hash,
                    "next_cursor": page.next_cursor,
                    "complete": page.complete,
                    "records": [_record_payload(item) for item in page.records],
                    "security_master_catalog_identifier": delivery.catalog.identifier,
                    "readiness_authority": False,
                },
            )
            checkpoint_payload = {
                "source_identifier": source.identifier,
                "next_cursor": page.next_cursor,
                "completed_at": (
                    page.retrieved_at.isoformat() if page.complete else None
                ),
                "catalog_identifier": delivery.catalog.identifier,
                "content_hash": event.content_hash,
            }
            _atomic_json(checkpoint_path, checkpoint_payload)
            results.append(
                PublicCatalogMaintenanceResult(
                    source_identifier=source.identifier,
                    state="stored",
                    record_count=len(page.records),
                    next_cursor=page.next_cursor,
                    complete=page.complete,
                    catalog_identifier=delivery.catalog.identifier,
                    content_hash=event.content_hash,
                )
            )
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            results.append(
                PublicCatalogMaintenanceResult(
                    source_identifier=source.identifier,
                    state="degraded",
                    record_count=0,
                    next_cursor=cursor,
                    complete=False,
                    catalog_identifier=None,
                    content_hash=None,
                    detail=f"{type(error).__name__}: {str(error)[:800]}",
                )
            )

    store.verify_integrity()
    report = GlobalPublicCatalogMaintenanceReport(
        evaluated_at=evaluated_at,
        results=tuple(results),
    )
    _atomic_json(root / "latest_report.json", report.to_dict())
    return report


__all__ = [
    "GlobalPublicCatalogMaintenanceReport",
    "PublicCatalogMaintenanceResult",
    "maintain_global_public_catalogs",
]
