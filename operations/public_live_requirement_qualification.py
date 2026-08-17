"""Qualify required public-live information one governed requirement group at a time.

Required public-live sources express provider fallback semantics through ``requirement_group``.
Each group is an independent durable operational unit: it is collected inside its own
killable process boundary, successful normalized records are merged immediately, and the
qualified group is committed before the next group is attempted. A timeout or provider
failure therefore cannot terminate qualification of unrelated requirements.

The module also publishes a credential-safe progress manifest after every state transition.
The manifest is observability only: it has no investment, specialist, construction,
execution, or real-money authority. Missing groups, stale checkpoints, exhausted fallbacks,
and timed-out workers remain fail-closed.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from operations import continuous_evidence_plane as _plane
from operations import qualified_evidence_ledger as _ledger
from operations.supervised_component_execution import (
    SupervisedComponentExecutionError,
    SupervisedComponentTimeout,
    run_supervised_component,
)
from providers.public_live_information import PublicLiveSourceCatalog
from providers.public_live_information_extended import ImpactfulPublicLiveInformationProvider
from providers.public_live_source_catalogs import load_operating_public_live_source_catalog
from public_live_record_history import merge_public_event_records


_COMPONENT_PREFIX = "required-public-live-group"
_COMPONENT_CONTRACT = "required-public-live-group.v2"
_PROGRESS_SCHEMA = "public-live-requirement-progress.v1"
_REQUIREMENT_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PUBLIC_REQUIREMENT_TIMEOUT_SECONDS"
_LEGACY_PUBLIC_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PUBLIC_TIMEOUT_SECONDS"
_DEFAULT_REQUIREMENT_TIMEOUT_SECONDS = 75.0


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
        str(
            values.get("CAPITAL_INTELLIGENCE_DATA_DIR")
            or os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
        )
    ).expanduser()
    return data_dir / default_name


def _data_dir(values: Mapping[str, str]) -> Path:
    return Path(
        str(
            values.get("CAPITAL_INTELLIGENCE_DATA_DIR")
            or os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
        )
    ).expanduser()


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
    """Return every required-information group in deterministic catalog order."""

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
    return _data_dir(values) / "public_live_requirements" / f"{_safe(requirement_group)}.json"


def public_live_requirement_progress_path(values: Mapping[str, str]) -> Path:
    return _data_dir(values) / "public_live_requirements" / "latest-status.json"


def load_public_live_requirement_progress(
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object] | None:
    resolved = os.environ if values is None else values
    path = public_live_requirement_progress_path(resolved)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _PROGRESS_SCHEMA:
        return None
    if payload.get("credential_safe") is not True:
        return None
    if payload.get("paper_only") is not True or payload.get("real_money_authorized") is not False:
        return None
    return dict(payload)


def _group_sources(catalog: object, requirement_group: str) -> tuple[object, ...]:
    group = str(requirement_group).strip()
    return tuple(
        source
        for source in tuple(getattr(catalog, "sources", ()) or ())
        if bool(getattr(source, "required", False))
        and str(getattr(source, "requirement_group", "") or "").strip() == group
    )


def _component_name(requirement_group: str) -> str:
    return f"{_COMPONENT_PREFIX}::{_safe(requirement_group)}"


def _component_compatibility(catalog: object, requirement_group: str) -> str:
    sources = _group_sources(catalog, requirement_group)
    contract = [
        {
            "identifier": str(getattr(source, "identifier", "")),
            "parser": str(getattr(source, "parser", "")),
            "endpoint": str(getattr(source, "endpoint", "")),
            "enabled": bool(getattr(source, "enabled", False)),
            "required": bool(getattr(source, "required", False)),
            "requirement_group": str(getattr(source, "requirement_group", "") or ""),
            "credential_environment_variables": list(
                getattr(source, "credential_environment_variables", ()) or ()
            ),
            "parameters": dict(getattr(source, "parameters", {}) or {}),
            "headers": dict(getattr(source, "headers", {}) or {}),
            "maximum_records": int(getattr(source, "maximum_records", 0) or 0),
        }
        for source in sources
    ]
    return _ledger.compatibility_fingerprint(
        _COMPONENT_CONTRACT,
        str(getattr(catalog, "identifier", "")),
        requirement_group,
        contract,
    )


def _configured_provider_order(catalog: object, requirement_group: str) -> tuple[str, ...]:
    return tuple(_safe(getattr(source, "identifier", "")) for source in _group_sources(catalog, requirement_group))


def _requirement_timeout_seconds(values: Mapping[str, str]) -> float:
    raw = str(
        values.get(_REQUIREMENT_TIMEOUT_ENV)
        or os.getenv(_REQUIREMENT_TIMEOUT_ENV, "")
        or values.get(_LEGACY_PUBLIC_TIMEOUT_ENV)
        or os.getenv(_LEGACY_PUBLIC_TIMEOUT_ENV, "")
    ).strip()
    if not raw:
        return _DEFAULT_REQUIREMENT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ValueError(f"{_REQUIREMENT_TIMEOUT_ENV} must be numeric") from error
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError(f"{_REQUIREMENT_TIMEOUT_ENV} must be positive")
    return timeout


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
    *, requirement_group: str, as_of: datetime, values: Mapping[str, str]
) -> Mapping[str, object]:
    """Collect exactly one required-information group and persist its normalized records."""

    group = str(requirement_group).strip()
    if not group:
        raise ValueError("requirement_group must be non-empty")
    _aware(as_of, field_name="public_requirement_cutoff")
    catalog = _catalog(values)
    selected = _group_sources(catalog, group)
    if not selected:
        raise _plane.ContinuousEvidencePlaneError(
            f"required public live information group is absent; required_information={_safe(group)}"
        )

    scoped_catalog = PublicLiveSourceCatalog(
        identifier=str(getattr(catalog, "identifier", "")), sources=selected
    )
    report = ImpactfulPublicLiveInformationProvider(scoped_catalog).collect(include_optional=False)
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
    successful = next((item for item in members if bool(getattr(item, "succeeded", False))), None)
    if successful is None or getattr(report, "required_sources_ready", None) is not True:
        configured_order = tuple(_safe(getattr(source, "identifier", "")) for source in selected)
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
    prior_attempts = attempted[:provider_index] if provider_index > 0 else ()
    current_record_count = _write_rolling_records(values=values, report=report, requirement_group=group)
    evaluated_at = _aware(getattr(report, "evaluated_at"), field_name="public_requirement_evaluated_at")
    payload: dict[str, object] = {
        "schema_version": "public-live-requirement-qualification.v1",
        "required_information": group,
        "qualified": True,
        "provider": provider,
        "fallback_providers_attempted": list(prior_attempts),
        "source_identifiers": [_safe(getattr(source, "identifier", "")) for source in selected],
        "evaluated_at": evaluated_at.isoformat(),
        "record_count": current_record_count,
        "catalog_identifier": str(getattr(catalog, "identifier", "")),
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    report_path = _requirement_report_path(values, group)
    _atomic_json(report_path, payload)
    payload["report_path"] = str(report_path)
    return payload


def _qualify_and_checkpoint_requirement(
    *, requirement_group: str, as_of: datetime, values: Mapping[str, str], compatibility: str
) -> Mapping[str, object]:
    payload = collect_required_public_live_requirement(
        requirement_group=requirement_group, as_of=as_of, values=values
    )
    try:
        evaluated_at = datetime.fromisoformat(str(payload.get("evaluated_at") or "").replace("Z", "+00:00"))
    except ValueError as error:
        raise _plane.ContinuousEvidencePlaneError(
            "qualified public requirement returned an invalid evaluation timestamp"
        ) from error
    evaluated_at = _aware(evaluated_at, field_name="public_requirement_component_as_of")
    try:
        component = _ledger.publish_qualified_component(
            values=values,
            component_name=_component_name(requirement_group),
            compatibility=compatibility,
            as_of=evaluated_at,
            payload=payload,
        )
    except _ledger.QualifiedEvidenceLedgerError as error:
        raise _plane.ContinuousEvidencePlaneError(
            "required public live checkpoint cannot be committed; "
            f"required_information={_safe(requirement_group)}: {error}"
        ) from error
    return {**dict(payload), "component_id": component.component_id, "valid_through": component.valid_through.isoformat()}


def _supervised_qualify_and_checkpoint_requirement(
    *,
    requirement_group: str,
    as_of: datetime,
    values: Mapping[str, str],
    compatibility: str,
    catalog: object,
) -> Mapping[str, object]:
    providers = _configured_provider_order(catalog, requirement_group)
    primary = providers[0] if providers else "unknown"
    fallback_detail = ",".join(providers[1:]) if len(providers) > 1 else "none"
    try:
        result = run_supervised_component(
            component=_component_name(requirement_group),
            operation=lambda: _qualify_and_checkpoint_requirement(
                requirement_group=requirement_group,
                as_of=as_of,
                values=values,
                compatibility=compatibility,
            ),
            timeout_seconds=_requirement_timeout_seconds(values),
            return_value=True,
        )
    except SupervisedComponentTimeout as error:
        raise _plane.ContinuousEvidencePlaneError(
            "required public live requirement acquisition timed out; failure_type=timeout; "
            f"required_information={_safe(requirement_group)}; provider={primary}; "
            f"fallback_providers_attempted={fallback_detail}"
        ) from error
    except SupervisedComponentExecutionError as error:
        detail = str(error)
        if "required_information=" in detail:
            raise _plane.ContinuousEvidencePlaneError(detail) from error
        raise _plane.ContinuousEvidencePlaneError(
            "required public live requirement acquisition failed; failure_type=provider_failure; "
            f"required_information={_safe(requirement_group)}; provider={primary}; "
            f"fallback_providers_attempted={fallback_detail}"
        ) from error
    if not isinstance(result, Mapping):
        raise _plane.ContinuousEvidencePlaneError(
            "required public live requirement worker returned an invalid result; "
            f"required_information={_safe(requirement_group)}"
        )
    return dict(result)


def finalize_required_public_live_requirements(
    *, requirement_groups: tuple[str, ...], as_of: datetime, values: Mapping[str, str]
) -> None:
    """Mark the rolling record set ready only after every required group qualified."""

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


def _failure_record(group: str, detail: str, catalog: object) -> dict[str, object]:
    providers = _configured_provider_order(catalog, group)
    provider = providers[0] if providers else "unknown"
    fallbacks = list(providers[1:])
    provider_match = re.search(r"(?:^|;\s*)provider=([^;\s]+)", detail)
    fallback_match = re.search(r"(?:^|;\s*)fallback_providers_attempted=([^;\s]+)", detail)
    failure_match = re.search(r"(?:^|;\s*)failure_type=([^;\s]+)", detail)
    if provider_match:
        provider = _safe(provider_match.group(1))
    if fallback_match:
        raw = fallback_match.group(1).strip()
        fallbacks = [] if raw in {"", "none"} else [_safe(item) for item in raw.split(",") if item]
    return {
        "required_information": _safe(group),
        "provider": provider,
        "fallback_providers_attempted": fallbacks,
        "failure_type": _safe(failure_match.group(1) if failure_match else "provider_failure"),
    }


def _write_progress(
    *,
    values: Mapping[str, str],
    cutoff: datetime,
    groups: tuple[str, ...],
    qualified: list[str],
    reused_count: int,
    newly_qualified_count: int,
    failures: list[dict[str, object]],
    active: str | None,
    state: str,
) -> None:
    failed_groups = [str(item.get("required_information") or "") for item in failures]
    completed = set(qualified) | set(failed_groups)
    pending = [group for group in groups if group not in completed]
    _atomic_json(
        public_live_requirement_progress_path(values),
        {
            "schema_version": _PROGRESS_SCHEMA,
            "state": state,
            "cutoff": cutoff.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "required_count": len(groups),
            "qualified_count": len(qualified),
            "reused_count": reused_count,
            "newly_qualified_count": newly_qualified_count,
            "failed_count": len(failures),
            "pending_count": len(pending),
            "active_required_information": None if active is None else _safe(active),
            "qualified_required_information": [_safe(group) for group in qualified],
            "failed_required_information": failed_groups,
            "failures": failures,
            "credential_safe": True,
            "decision_evidence_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )


def maintain_required_public_live_requirements(
    *, as_of: datetime, values: Mapping[str, str]
):
    """Converge all independent requirements, then expose one fail-closed aggregate."""

    cutoff = _aware(as_of, field_name="public_requirements_as_of")
    catalog = _catalog(values)
    groups = required_public_live_requirement_groups(values)
    records_exist = _records_path(values).exists()
    component_ids: list[str] = []
    providers: list[str] = []
    fallback_attempted = False
    reused_count = 0
    newly_qualified_count = 0
    qualified_groups: list[str] = []
    failures: list[tuple[str, str]] = []
    failure_records: list[dict[str, object]] = []

    _write_progress(
        values=values,
        cutoff=cutoff,
        groups=groups,
        qualified=qualified_groups,
        reused_count=0,
        newly_qualified_count=0,
        failures=failure_records,
        active=None,
        state="qualifying",
    )

    for group in groups:
        compatibility = _component_compatibility(catalog, group)
        component = None
        if records_exist:
            try:
                component = _ledger.load_qualified_component(
                    values=values,
                    component_name=_component_name(group),
                    compatibility=compatibility,
                    cutoff=datetime.now(timezone.utc),
                )
            except _ledger.QualifiedEvidenceLedgerError as error:
                detail = (
                    "required public live checkpoint is invalid; "
                    f"required_information={_safe(group)}: {error}"
                )
                failures.append((group, detail))
                failure_records.append(_failure_record(group, detail, catalog))
                _write_progress(
                    values=values, cutoff=cutoff, groups=groups,
                    qualified=qualified_groups, reused_count=reused_count,
                    newly_qualified_count=newly_qualified_count, failures=failure_records,
                    active=None, state="qualifying",
                )
                continue
        if component is None:
            _write_progress(
                values=values, cutoff=cutoff, groups=groups,
                qualified=qualified_groups, reused_count=reused_count,
                newly_qualified_count=newly_qualified_count, failures=failure_records,
                active=group, state="qualifying",
            )
            try:
                result = _supervised_qualify_and_checkpoint_requirement(
                    requirement_group=group,
                    as_of=cutoff,
                    values=values,
                    compatibility=compatibility,
                    catalog=catalog,
                )
            except _plane.ContinuousEvidencePlaneError as error:
                detail = str(error)
                failures.append((group, detail))
                failure_records.append(_failure_record(group, detail, catalog))
                _write_progress(
                    values=values, cutoff=cutoff, groups=groups,
                    qualified=qualified_groups, reused_count=reused_count,
                    newly_qualified_count=newly_qualified_count, failures=failure_records,
                    active=None, state="qualifying",
                )
                continue
            newly_qualified_count += 1
            component_id = str(result.get("component_id") or "").strip()
            provider = str(result.get("provider") or "").strip()
            fallbacks = tuple(result.get("fallback_providers_attempted") or ())
        else:
            reused_count += 1
            component_id = component.component_id
            provider = str(component.payload.get("provider") or "").strip()
            fallbacks = tuple(component.payload.get("fallback_providers_attempted") or ())
        if not component_id:
            detail = (
                "required public live checkpoint lost its identifier; "
                f"required_information={_safe(group)}"
            )
            failures.append((group, detail))
            failure_records.append(_failure_record(group, detail, catalog))
            continue
        component_ids.append(component_id)
        qualified_groups.append(group)
        if provider:
            providers.append(provider)
        fallback_attempted = fallback_attempted or bool(fallbacks)
        _write_progress(
            values=values, cutoff=cutoff, groups=groups,
            qualified=qualified_groups, reused_count=reused_count,
            newly_qualified_count=newly_qualified_count, failures=failure_records,
            active=None, state="qualifying",
        )

    if failures:
        failed_groups = ",".join(_safe(group) for group, _detail in failures)
        first_group, first_detail = failures[0]
        _write_progress(
            values=values, cutoff=cutoff, groups=groups,
            qualified=qualified_groups, reused_count=reused_count,
            newly_qualified_count=newly_qualified_count, failures=failure_records,
            active=None, state="incomplete",
        )
        raise _plane.ContinuousEvidencePlaneError(
            "required public live requirements remain incomplete after independent qualification; "
            f"required_requirement_count={len(groups)}; qualified_requirement_count={len(qualified_groups)}; "
            f"reused_requirement_count={reused_count}; newly_qualified_requirement_count={newly_qualified_count}; "
            f"failed_requirement_count={len(failures)}; failed_required_information={failed_groups}; "
            f"required_information={_safe(first_group)}; {first_detail}"
        )

    finalize_required_public_live_requirements(requirement_groups=groups, as_of=cutoff, values=values)
    _write_progress(
        values=values, cutoff=cutoff, groups=groups,
        qualified=qualified_groups, reused_count=reused_count,
        newly_qualified_count=newly_qualified_count, failures=failure_records,
        active=None, state="qualified",
    )
    return SimpleNamespace(
        state="degraded" if fallback_attempted else "available",
        required_sources_ready=True,
        failed_required_source_identifiers=(),
        collection_scope="required",
        qualified_requirement_groups=groups,
        qualified_requirement_component_ids=tuple(component_ids),
        qualified_requirement_reused_count=reused_count,
        qualified_requirement_new_count=newly_qualified_count,
        qualified_requirement_provider_identifiers=tuple(providers),
    )


__all__ = [
    "collect_required_public_live_requirement",
    "finalize_required_public_live_requirements",
    "load_public_live_requirement_progress",
    "maintain_required_public_live_requirements",
    "public_live_requirement_progress_path",
    "required_public_live_requirement_groups",
]
