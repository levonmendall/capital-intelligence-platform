"""Publish the credential-safe CIO diagnostic audit through Streamlit static files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from api.config import ApiSettings
from api.routes.cio_diagnostic import build_cio_diagnostic_audit
from operations.granular_futures_reference_prequalification import (
    load_futures_reference_progress,
)
from operations.reference_readiness import load_reference_readiness_progress
from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
)
from operations.supervised_reference_prequalification import (
    load_reference_prequalification_progress,
)


def audit_output_path(values: Mapping[str, str] | None = None) -> Path:
    resolved = os.environ if values is None else values
    configured = resolved.get(
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH",
        "",
    ).strip()
    return Path(configured or "static/cio-diagnostic.json").expanduser()


def _with_reference_progress(
    payload: Mapping[str, object],
    *,
    values: Mapping[str, str],
) -> dict[str, object]:
    """Surface pre-CIO reference progress only while canonical progress is absent."""

    published = dict(payload)
    if published.get("stage") not in (None, "", "awaiting_progress"):
        return published
    reference = load_reference_readiness_progress(values)
    if reference is None:
        return published
    stage = str(reference.get("stage") or "").strip()
    metrics = reference.get("progress_metrics")
    if not stage or not isinstance(metrics, Mapping):
        return published
    state = str(published.get("state") or "").strip().lower()
    if state not in {"pending", "in_progress", "failed"}:
        return published
    published["stage"] = stage
    published["progress_metrics"] = {
        str(name): int(value)
        for name, value in metrics.items()
        if isinstance(name, str)
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }
    published["reference_progress"] = True
    published["reference_progress_recorded_at"] = reference.get("updated_at")
    return published


def _parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_identifier(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        return None
    if not all(character.isalnum() or character in {"_", "-", ".", ":"} for character in text):
        return None
    return text


def _safe_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_root(value: object) -> str | None:
    root = str(value or "").strip().upper()
    if not root or len(root) > 16:
        return None
    if not all(character.isalnum() or character in {"-", "_"} for character in root):
        return None
    return root


def _safe_futures_reference_progress(
    values: Mapping[str, str],
) -> dict[str, object] | None:
    """Promote granular futures progress into a credential-safe certification DAG.

    The acquisition coordinator already persists successful roots independently. This
    publisher turns that durable execution record into one root-addressable public state
    without changing the strict all-roots qualification barrier.
    """

    progress = load_futures_reference_progress(values)
    if not isinstance(progress, Mapping):
        return None

    release_status = load_release_evidence_prequalification(values)
    if isinstance(release_status, Mapping):
        started_at = _parse_timestamp(release_status.get("started_at"))
        updated_at = _parse_timestamp(progress.get("updated_at"))
        if started_at is not None and (updated_at is None or updated_at < started_at):
            return None

    required_roots = [
        root
        for item in progress.get("required_roots", [])
        if (root := _safe_root(item)) is not None
    ] if isinstance(progress.get("required_roots"), list) else []
    qualified_roots = [
        root
        for item in progress.get("qualified_roots", [])
        if (root := _safe_root(item)) is not None
    ] if isinstance(progress.get("qualified_roots"), list) else []
    unresolved_roots = [
        root
        for item in progress.get("unresolved_roots", [])
        if (root := _safe_root(item)) is not None
    ] if isinstance(progress.get("unresolved_roots"), list) else []

    units: list[dict[str, object]] = []
    raw_units = progress.get("units")
    if isinstance(raw_units, list):
        for item in raw_units:
            if not isinstance(item, Mapping):
                continue
            roots = [
                root
                for raw_root in item.get("roots", [])
                if (root := _safe_root(raw_root)) is not None
            ] if isinstance(item.get("roots"), list) else []
            duration_ms = _safe_nonnegative_int(item.get("duration_ms"))
            http_status = _safe_nonnegative_int(item.get("http_status"))
            if http_status is not None and not 100 <= http_status <= 599:
                http_status = None
            retryable = item.get("retryable")
            units.append(
                {
                    "unit": _safe_identifier(item.get("unit")),
                    "provider": _safe_identifier(item.get("provider")),
                    "state": _safe_identifier(item.get("state")),
                    "venue": _safe_identifier(item.get("venue")),
                    "root": _safe_root(item.get("root")),
                    "roots": roots,
                    "duration_ms": duration_ms if duration_ms is not None else 0,
                    "failure_type": _safe_identifier(item.get("failure_type")),
                    "fallback": item.get("fallback") is True,
                    "provider_error_type": _safe_identifier(
                        item.get("provider_error_type")
                    ),
                    "http_status": http_status,
                    "retryable": retryable if isinstance(retryable, bool) else None,
                }
            )

    qualified_set = set(qualified_roots)
    unresolved_set = set(unresolved_roots)

    blocking: dict[str, object] | None = None
    for item in reversed(units):
        if item.get("state") not in {"failed", "timed-out", "invalid"}:
            continue
        root = item.get("root")
        roots = set(item.get("roots") or [])
        if root in unresolved_set or bool(roots.intersection(unresolved_set)):
            blocking = item
            break

    nodes: list[dict[str, object]] = []
    for root in required_roots:
        latest = next(
            (
                item
                for item in reversed(units)
                if item.get("root") == root or root in set(item.get("roots") or [])
            ),
            None,
        )
        if root in qualified_set:
            node_state = "qualified"
        elif latest is not None and latest.get("state") in {"failed", "timed-out", "invalid"}:
            node_state = latest.get("state")
        else:
            node_state = "pending"
        nodes.append(
            {
                "root": root,
                "state": node_state,
                "unit": None if latest is None else latest.get("unit"),
                "provider": None if latest is None else latest.get("provider"),
                "venue": None if latest is None else latest.get("venue"),
                "failure_type": None if latest is None else latest.get("failure_type"),
                "duration_ms": 0 if latest is None else latest.get("duration_ms", 0),
                "fallback": False if latest is None else latest.get("fallback") is True,
                "provider_error_type": (
                    None if latest is None else latest.get("provider_error_type")
                ),
                "http_status": None if latest is None else latest.get("http_status"),
                "retryable": None if latest is None else latest.get("retryable"),
            }
        )

    active_units = [
        identifier
        for item in progress.get("active_units", [])
        if (identifier := _safe_identifier(item)) is not None
    ] if isinstance(progress.get("active_units"), list) else []
    fallback_max_workers = _safe_nonnegative_int(progress.get("fallback_max_workers"))
    if fallback_max_workers is not None and not 1 <= fallback_max_workers <= 4:
        fallback_max_workers = None

    raw_timeout = str(
        values.get("CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS")
        or os.getenv("CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS", "")
        or "45"
    ).strip()
    try:
        unit_timeout_seconds = float(raw_timeout)
    except ValueError:
        unit_timeout_seconds = 45.0
    if unit_timeout_seconds <= 0:
        unit_timeout_seconds = 45.0

    return {
        "state": _safe_identifier(progress.get("state")),
        "updated_at": str(progress.get("updated_at") or "") or None,
        "cutoff": str(progress.get("cutoff") or "") or None,
        "required_root_count": len(required_roots),
        "qualified_root_count": len(qualified_roots),
        "unresolved_root_count": len(unresolved_roots),
        "required_roots": required_roots,
        "qualified_roots": qualified_roots,
        "unresolved_roots": unresolved_roots,
        "active_unit": _safe_identifier(progress.get("active_unit")),
        "active_units": active_units,
        "fallback_max_workers": fallback_max_workers,
        "unit_timeout_seconds": unit_timeout_seconds,
        "blocking_unit": None if blocking is None else blocking.get("unit"),
        "blocking_provider": None if blocking is None else blocking.get("provider"),
        "blocking_venue": None if blocking is None else blocking.get("venue"),
        "blocking_root": None if blocking is None else blocking.get("root"),
        "blocking_failure_type": (
            None if blocking is None else blocking.get("failure_type")
        ),
        "blocking_provider_error_type": (
            None if blocking is None else blocking.get("provider_error_type")
        ),
        "blocking_http_status": (
            None if blocking is None else blocking.get("http_status")
        ),
        "blocking_retryable": (
            None if blocking is None else blocking.get("retryable")
        ),
        "nodes": nodes,
        "units": units,
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _safe_reference_prequalification_progress(
    values: Mapping[str, str],
) -> dict[str, object] | None:
    progress = load_reference_prequalification_progress(values)
    if not isinstance(progress, Mapping):
        return None
    release_status = load_release_evidence_prequalification(values)
    if isinstance(release_status, Mapping):
        started_at = _parse_timestamp(release_status.get("started_at"))
        updated_at = _parse_timestamp(progress.get("updated_at"))
        if started_at is not None and (updated_at is None or updated_at < started_at):
            return None

    safe: dict[str, object] = {
        "state": _safe_identifier(progress.get("state")),
        "updated_at": str(progress.get("updated_at") or "") or None,
        "active_component": _safe_identifier(progress.get("active_component")),
    }
    for key in (
        "required_count",
        "qualified_count",
        "reused_count",
        "newly_qualified_count",
        "failed_count",
        "pending_count",
    ):
        value = progress.get(key)
        safe[key] = (
            int(value)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else 0
        )

    components: list[dict[str, object]] = []
    raw_components = progress.get("components")
    if isinstance(raw_components, list):
        for item in raw_components:
            if not isinstance(item, Mapping):
                continue
            components.append(
                {
                    "component": _safe_identifier(item.get("component")),
                    "provider": _safe_identifier(item.get("provider")),
                    "state": _safe_identifier(item.get("state")),
                    "required": item.get("required") is True,
                    "failure_type": _safe_identifier(item.get("failure_type")),
                }
            )
    safe["components"] = components
    safe["failures"] = [
        {
            "component": item["component"],
            "provider": item["provider"],
            "failure_type": item["failure_type"],
        }
        for item in components
        if item.get("state") in {"failed", "timed-out", "invalid"}
    ]
    return safe


def _with_release_prequalification(
    payload: Mapping[str, object],
    *,
    values: Mapping[str, str],
) -> dict[str, object]:
    """Expose release evidence work without manufacturing a CIO request.

    The public audit uses the prequalification identifier as a generic polling identity so
    deployment verification can observe fresh progress. Internally no manual CIO request
    exists until evidence_generation_ready has been published.
    """

    status = load_release_evidence_prequalification(values)
    if status is None:
        return dict(payload)

    started_at = _parse_timestamp(status.get("started_at"))
    canonical_requested_at = _parse_timestamp(payload.get("requested_at"))
    canonical_current = bool(
        str(payload.get("active_release") or "") == str(status.get("release") or "")
        and payload.get("release_matches") is True
        and str(payload.get("request_id") or "").strip()
        and started_at is not None
        and canonical_requested_at is not None
        and canonical_requested_at >= started_at
    )
    if canonical_current:
        return dict(payload)

    state = str(status.get("state") or "").strip().lower()
    if state not in {"pending", "in_progress", "completed", "failed"}:
        return dict(payload)

    published = dict(payload)
    reference = load_reference_readiness_progress(values)
    component_stage = None
    component_metrics: dict[str, int] = {}
    if isinstance(reference, Mapping):
        reference_updated = _parse_timestamp(reference.get("updated_at"))
        if (
            started_at is not None
            and reference_updated is not None
            and reference_updated >= started_at
        ):
            raw_stage = str(reference.get("stage") or "").strip()
            raw_metrics = reference.get("progress_metrics")
            if raw_stage:
                component_stage = raw_stage
            if isinstance(raw_metrics, Mapping):
                component_metrics = {
                    str(name): int(value)
                    for name, value in raw_metrics.items()
                    if isinstance(name, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                }

    futures_reference = _safe_futures_reference_progress(values)
    raw_failure_context = status.get("failure_context")
    failure_context: dict[str, object] | None = None
    if isinstance(raw_failure_context, Mapping):
        failure_context = dict(raw_failure_context)
        failure_context["component_stage"] = component_stage
        failure_context["component_metrics"] = component_metrics
        if futures_reference is not None:
            failure_context["futures_reference"] = futures_reference

    public_state = "failed" if state == "failed" else "prequalifying"
    published.update(
        {
            "request_id": str(status.get("prequalification_id") or ""),
            "request_kind": "evidence_prequalification",
            "requested_at": status.get("started_at"),
            "completed_at": status.get("completed_at") if state == "failed" else None,
            "active_release": status.get("release"),
            "release_matches": True,
            "state": public_state,
            "stage": status.get("stage"),
            "detail": status.get("detail"),
            "progress_metrics": dict(status.get("metrics") or {}),
            "prequalification_component_stage": component_stage,
            "prequalification_component_metrics": component_metrics,
            "prequalification_generation_id": status.get("generation_id"),
            "prequalification_state": state,
            "prequalification_active": state in {"pending", "in_progress", "completed"},
            "prequalification_failure_context": failure_context,
            "prequalification_failure_reason": (
                None if failure_context is None else failure_context.get("reason")
            ),
            "prequalification_failure_capability": (
                None if failure_context is None else failure_context.get("capability")
            ),
            "prequalification_failure_stage": (
                None if failure_context is None else failure_context.get("failure_stage")
            ),
            "prequalification_failure_provider": (
                None if failure_context is None else failure_context.get("provider")
            ),
            "prequalification_failure_error_type": (
                None if failure_context is None else failure_context.get("error_type")
            ),
            "prequalification_failure_unit": (
                None if futures_reference is None else futures_reference.get("blocking_unit")
            ),
            "prequalification_failure_venue": (
                None if futures_reference is None else futures_reference.get("blocking_venue")
            ),
            "prequalification_failure_root": (
                None if futures_reference is None else futures_reference.get("blocking_root")
            ),
            "prequalification_unresolved_futures_roots": (
                [] if futures_reference is None else futures_reference.get("unresolved_roots", [])
            ),
            "ready": False,
            "context_cycle_matches": False,
            "context_attempt_cycle_matches": False,
            "comprehensive_discovery_complete": False,
            "scheduled_market_coverage_complete": False,
            "terminal_screening_complete": False,
            "all_market_evaluation_complete": False,
            "all_market_certification_context_matches": False,
            "all_market_certification_v2_context_matches": False,
            "market_lanes": [],
            "paper_only": True,
            "real_money_authorized": False,
            "credential_safe": True,
        }
    )
    return published


def _paper_implementation_complete(payload: Mapping[str, object]) -> bool:
    """Report terminal implementation truth without gating analytical certification.

    A governed no-action outcome is terminal operational completion just like completed
    paper implementation. Scheduled/held/blocked implementation remains explicitly false.
    """

    return bool(
        payload.get("all_market_operational_certified") is True
        and (
            payload.get("all_market_paper_implementation_certified") is True
            or payload.get("all_market_no_action_certified") is True
        )
    )


def publish_cio_diagnostic_audit(
    *,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Publish the canonical credential-safe audit without reinterpreting authority.

    ``build_cio_diagnostic_audit`` is the single composition point for lifecycle,
    all-market lane integrity, certification-v2 lineage, and analytical readiness. This
    static publisher only adds prequalification progress, terminal implementation display,
    publication time, and filesystem delivery for the public Render verifier.
    """

    resolved = os.environ if values is None else values
    settings = ApiSettings.from_env(resolved)
    payload = _with_reference_progress(
        build_cio_diagnostic_audit(settings=settings, values=resolved),
        values=resolved,
    )
    payload = _with_release_prequalification(payload, values=resolved)
    reference_prequalification = _safe_reference_prequalification_progress(resolved)
    futures_reference = _safe_futures_reference_progress(resolved)
    public_prequalification = payload.get("public_live_requirement_progress")
    active_phase = "unknown"
    if isinstance(reference_prequalification, Mapping):
        reference_state = str(reference_prequalification.get("state") or "")
        if reference_state != "qualified":
            active_phase = "reference"
        elif isinstance(public_prequalification, Mapping):
            active_phase = (
                "complete"
                if str(public_prequalification.get("state") or "") == "qualified"
                else "public_live"
            )
        else:
            active_phase = "public_live"
    elif isinstance(public_prequalification, Mapping):
        active_phase = "public_live"

    paper_implementation_complete = _paper_implementation_complete(payload)
    analytical_complete = payload.get("all_market_evaluation_complete") is True
    published = {
        **payload,
        "reference_prequalification_progress": reference_prequalification,
        "futures_reference_progress": futures_reference,
        "prequalification_progress": {
            "active_phase": active_phase,
            "reference": reference_prequalification,
            "futures_reference": futures_reference,
            "public_live": public_prequalification,
        },
        "paper_implementation_complete": paper_implementation_complete,
        "all_market_evaluation_complete": analytical_complete,
        "ready": analytical_complete,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "public-cio-diagnostic-audit.v2-end-to-end",
        "credential_safe": True,
    }
    path = audit_output_path(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(published, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return published


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError("publish_cio_diagnostic_audit.py accepts no arguments")
    try:
        payload = publish_cio_diagnostic_audit()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "cio_diagnostic_audit_publication_failed",
                    "error_type": type(error).__name__,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "cio_diagnostic_audit_published",
                "active_release": payload.get("active_release"),
                "state": payload.get("state"),
                "stage": payload.get("stage"),
                "request_kind": payload.get("request_kind"),
                "all_market_runtime_certified": payload.get(
                    "all_market_runtime_certified"
                ),
                "all_market_certification_context_matches": payload.get(
                    "all_market_certification_context_matches"
                ),
                "all_market_certification_v2_state": payload.get(
                    "all_market_certification_v2_state"
                ),
                "all_market_construction_certified": payload.get(
                    "all_market_construction_certified"
                ),
                "all_market_operational_certified": payload.get(
                    "all_market_operational_certified"
                ),
                "paper_implementation_complete": payload.get(
                    "paper_implementation_complete"
                ),
                "all_market_evaluation_complete": payload.get(
                    "all_market_evaluation_complete"
                ),
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
