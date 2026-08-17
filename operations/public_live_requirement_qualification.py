"""Qualify required public-live information one governed requirement group at a time.

Required public-live sources already express provider fallback semantics through
``requirement_group``.  This module turns those groups into durable operational units:
each group is collected independently, successful normalized records are merged into the
existing rolling public record set immediately, and callers can checkpoint each qualified
group before attempting the next one.

Nothing here has investment, specialist, construction, execution, or real-money authority.
A requirement group is qualified only when at least one configured source in that exact
group succeeds.  Missing groups and exhausted fallbacks remain fail-closed.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from operations import continuous_evidence_plane as _plane
from providers.public_live_information import PublicLiveSourceCatalog
from providers.public_live_information_extended import ImpactfulPublicLiveInformationProvider
from providers.public_live_source_catalogs import load_operating_public_live_source_catalog
from public_live_record_history import merge_public_event_records


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return normalized.strip("-.") or "unknown"


def _data_path(values: Mapping[str, str], environment_name: str, default_name: str) -> Path:
    configured = str(values.get(environment_name) or os.getenv(environment_name, "")).strip()
    if configured:
        return Path(configured).expanduser()
    data_dir = Path(
        str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    ).expanduser()
    return data_dir / default_name


def _catalog(values: Mapping[str, str]):
    catalog_path = str(
        values.get("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_SOURCE_CATALOG")
        or os.getenv(
            "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_SOURCE_CATALOG",
            "config/public_live_information_sources.json",
        )
    ).strip()
    return load_operating_public_live_source_catalog(catalog_path)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise _plane.ContinuousEvidencePlaneError(
            f"required public live requirement state cannot be persisted: {error}"
        ) from error


def required_public_live_requirement_groups(values: Mapping[str, str]) -> tuple[str, ...]:
    """Return every configured required-information group in deterministic catalog order."""

    groups: list[str] = []
    for source in _catalog(values).sources:
        group = str(source.requirement_group or "").strip()
        if source.required and group and group not in groups:
            groups.append(group)
    if not groups:
        raise _plane.ContinuousEvidencePlaneError(
            "required public live catalog contains no governed requirement groups"
        )
    return tuple(groups)


def _records_path(values: Mapping[str, str]) -> Path:
    return _data_path(
        values,
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS",
        "public-live-information-records.json",
    )


def _requirement_report_path(values: Mapping[str, str], requirement_group: str) -> Path:
    data_dir = Path(
        str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    ).expanduser()
    return data_dir / "public_live_requirements" / f"{_safe(requirement_group)}.json"


def _write_rolling_records(
    *,
    values: Mapping[str, str],
    report: object,
    requirement_group: str,
) -> int:
    records_path = _records_path(values)
    evaluated_at = _aware(
        getattr(report, "evaluated_at"),
        field_name="public_requirement_evaluated_at",
    )
    current_records = [item.to_dict() for item in tuple(getattr(report, "records", ()) or ())]
    rolling_records = merge_public_event_records(
        records_path,
        current_records,
        evaluated_at=evaluated_at,
    )
    _atomic_json(
        records_path,
        {
            "schema_version": "public-live-information-record-set.v2",
            "catalog_identifier": str(getattr(report, "catalog_identifier", "")),
            "evaluated_at": evaluated_at.isoformat(),
            "records": rolling_records,
            "coverage": {
                "required_sources_ready": False,
                "qualified_requirement_group": requirement_group,
                "current_record_count": len(current_records),
                "rolling_record_count": len(rolling_records),
                "collection_scope": "required",
            },
            "decision_evidence_authority": False,
            "full_article_text_stored": False,
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        },
    )
    return len(current_records)


def collect_required_public_live_requirement(
    *,
    requirement_group: str,
    as_of: datetime,
    values: Mapping[str, str],
) -> Mapping[str, object]:
    """Collect exactly one required-information group and persist its normalized records."""

    group = str(requirement_group).strip()
    if not group:
        raise ValueError("requirement_group must be non-empty")
    _aware(as_of, field_name="public_requirement_cutoff")
    catalog = _catalog(values)
    selected = tuple(
        source
        for source in catalog.sources
        if source.required and str(source.requirement_group or "").strip() == group
    )
    if not selected:
        raise _plane.ContinuousEvidencePlaneError(
            f"required public live information group is absent; required_information={_safe(group)}"
        )

    scoped_catalog = PublicLiveSourceCatalog(
        identifier=catalog.identifier,
        sources=selected,
    )
    report = ImpactfulPublicLiveInformationProvider(scoped_catalog).collect(
        include_optional=False
    )
    members = tuple(
        item
        for item in tuple(getattr(report, "sources", ()) or ())
        if str(getattr(item, "requirement_group", "") or "").strip() == group
    )
    attempted = tuple(
        dict.fromkeys(
            identifier
            for item in members
            if (identifier := _safe(getattr(item, "source_identifier", ""))) != "unknown"
        )
    )
    successful = next(
        (item for item in members if bool(getattr(item, "succeeded", False))),
        None,
    )
    if successful is None or getattr(report, "required_sources_ready", None) is not True:
        configured_order = tuple(_safe(source.identifier) for source in selected)
        failures = attempted or configured_order
        primary = failures[0] if failures else "unknown"
        fallbacks = failures[1:]
        fallback_detail = ",".join(fallbacks) if fallbacks else "none"
        raise _plane.ContinuousEvidencePlaneError(
            "required public live information is not qualified; "
            f"required_information={_safe(group)}; provider={primary}; "
            f"fallback_providers_attempted={fallback_detail}"
        )

    provider = _safe(getattr(successful, "source_identifier", ""))
    provider_index = attempted.index(provider) if provider in attempted else 0
    fallbacks_attempted = attempted[1 : provider_index + 1] if provider_index > 0 else ()
    current_record_count = _write_rolling_records(
        values=values,
        report=report,
        requirement_group=group,
    )
    evaluated_at = _aware(
        getattr(report, "evaluated_at"),
        field_name="public_requirement_evaluated_at",
    )
    payload: dict[str, object] = {
        "schema_version": "public-live-requirement-qualification.v1",
        "required_information": group,
        "qualified": True,
        "provider": provider,
        "fallback_providers_attempted": list(fallbacks_attempted),
        "source_identifiers": [_safe(source.identifier) for source in selected],
        "evaluated_at": evaluated_at.isoformat(),
        "record_count": current_record_count,
        "catalog_identifier": catalog.identifier,
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    report_path = _requirement_report_path(values, group)
    _atomic_json(report_path, payload)
    payload["report_path"] = str(report_path)
    return payload


def finalize_required_public_live_requirements(
    *,
    requirement_groups: tuple[str, ...],
    as_of: datetime,
    values: Mapping[str, str],
) -> None:
    """Mark the shared rolling record set ready only after every required group qualified."""

    cutoff = _aware(as_of, field_name="public_requirements_cutoff")
    groups = tuple(dict.fromkeys(str(item).strip() for item in requirement_groups if str(item).strip()))
    if not groups:
        raise _plane.ContinuousEvidencePlaneError(
            "required public live aggregate cannot qualify without requirement groups"
        )
    records_path = _records_path(values)
    try:
        payload = json.loads(records_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
        raise _plane.ContinuousEvidencePlaneError(
            "required public live aggregate has no persisted normalized record set"
        ) from error
    if not isinstance(payload, Mapping):
        raise _plane.ContinuousEvidencePlaneError(
            "required public live aggregate record set is not an object"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise _plane.ContinuousEvidencePlaneError(
            "required public live aggregate record set has invalid records"
        )
    coverage = dict(payload.get("coverage") or {}) if isinstance(payload.get("coverage"), Mapping) else {}
    coverage.update(
        {
            "required_sources_ready": True,
            "qualified_requirement_groups": list(groups),
            "qualified_requirement_group_count": len(groups),
            "rolling_record_count": len(records),
            "collection_scope": "required",
        }
    )
    _atomic_json(
        records_path,
        {
            **dict(payload),
            "evaluated_at": cutoff.isoformat(),
            "coverage": coverage,
            "decision_evidence_authority": False,
            "full_article_text_stored": False,
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        },
    )


__all__ = [
    "collect_required_public_live_requirement",
    "finalize_required_public_live_requirements",
    "required_public_live_requirement_groups",
]
