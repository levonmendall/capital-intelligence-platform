"""Publish the credential-safe CIO diagnostic audit through Streamlit static files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from api.config import ApiSettings
from api.routes.cio_diagnostic import build_cio_diagnostic_audit
from operations.all_market_certification_audit import public_all_market_certification
from operations.reference_readiness import load_reference_readiness_progress
from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
)
from production_context_publication_runtime import _load_json, _state_path


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

    # "prequalifying" is intentionally not a CIO active state. It keeps the verifier
    # polling while ensuring the core verifier does not adopt this identity as the later
    # manual CIO request identity.
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
            "ready": False,
            "context_cycle_matches": False,
            "context_attempt_cycle_matches": False,
            "comprehensive_discovery_complete": False,
            "scheduled_market_coverage_complete": False,
            "terminal_screening_complete": False,
            "all_market_evaluation_complete": False,
            "market_lanes": [],
            "paper_only": True,
            "real_money_authorized": False,
            "credential_safe": True,
        }
    )
    return published


def _paper_implementation_complete(payload: Mapping[str, object]) -> bool:
    if str(payload.get("state") or "") != "completed":
        return False
    detail = str(payload.get("detail") or "")
    return detail in {
        "CIO diagnostic completed; paper_execution=completed.",
        "CIO diagnostic completed; paper_execution=no_action.",
    }


def _certificate_matches_current_context(
    *,
    payload: Mapping[str, object],
    certification: Mapping[str, object],
    context: Mapping[str, object],
) -> bool:
    """Bind the immutable lane proof to this diagnostic's exact discovery state."""

    decision_as_of = _parse_timestamp(context.get("decision_as_of"))
    certification_epoch = _parse_timestamp(
        certification.get("all_market_certification_epoch")
    )
    discovery_fingerprint = str(
        context.get("comprehensive_discovery_manifest_fingerprint") or ""
    ).strip()
    certified_fingerprint = str(
        certification.get("all_market_certification_discovery_manifest_fingerprint")
        or ""
    ).strip()
    return bool(
        payload.get("context_cycle_matches") is True
        and decision_as_of is not None
        and certification_epoch is not None
        and certification_epoch <= decision_as_of
        and discovery_fingerprint
        and certified_fingerprint == discovery_fingerprint
    )


def _load_persisted_context(settings: object) -> Mapping[str, object]:
    """Read the context proof if available; missing operational state stays fail-closed."""

    try:
        context = _load_json(_state_path(settings))
    except (AttributeError, OSError, TypeError, ValueError):
        return {}
    return context if isinstance(context, Mapping) else {}


def publish_cio_diagnostic_audit(
    *,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    resolved = os.environ if values is None else values
    settings = ApiSettings.from_env(resolved)
    payload = _with_reference_progress(
        build_cio_diagnostic_audit(settings=settings, values=resolved),
        values=resolved,
    )
    payload = _with_release_prequalification(payload, values=resolved)
    certification = public_all_market_certification(resolved)
    persisted_context = _load_persisted_context(settings)
    certification_context_matches = _certificate_matches_current_context(
        payload=payload,
        certification=certification,
        context=persisted_context,
    )
    paper_implementation_complete = _paper_implementation_complete(payload)
    end_to_end_complete = bool(
        payload.get("all_market_evaluation_complete") is True
        and certification.get("all_market_runtime_certified") is True
        and certification.get("all_market_certification_integrity_valid") is True
        and certification.get("all_market_certification_release_matches") is True
        and certification_context_matches
        and paper_implementation_complete
    )
    published = {
        **payload,
        **certification,
        "all_market_certification_context_matches": certification_context_matches,
        "paper_implementation_complete": paper_implementation_complete,
        "all_market_evaluation_complete": end_to_end_complete,
        "ready": end_to_end_complete,
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