"""Canonical read-only all-market certification provenance for presentation surfaces.

The envelope is a projection of independently produced certification-v2 audit evidence.
It never advances certification, contacts a provider, changes a threshold, authorizes a
portfolio decision, or grants execution authority. Missing, partial, stale, corrupt, or
cross-release evidence always projects to ``certified=False``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from cio.models import CandidateAssetClass
from operations.all_market_certification_readonly import (
    public_all_market_certification_readonly,
    resolve_latest_certification_readonly,
)
from operations.certification_runtime_state import CertificationRuntimeStateError


_SCHEMA_VERSION = "all-market-certification-envelope.v1"
_REQUIRED_MARKET_COUNT = sum(
    1 for item in CandidateAssetClass if item is not CandidateAssetClass.OTHER
)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _lanes(audit: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = audit.get("all_market_certified_lanes")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _identity(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def build_all_market_certification_envelope(
    audit: Mapping[str, Any] | None,
    *,
    values: Mapping[str, str] | None = None,
    verifier_source_id: str | None = None,
) -> dict[str, Any]:
    """Project validated certification telemetry into one fail-closed UI contract."""

    resolved_values = dict(os.environ if values is None else values)
    resolved_audit: Mapping[str, Any] = audit if isinstance(audit, Mapping) else {}
    lanes = _lanes(resolved_audit)
    lane_names = tuple(
        str(item.get("asset_class") or "").strip()
        for item in lanes
        if str(item.get("asset_class") or "").strip()
    )
    represented_count = len(set(lane_names))
    complete_denominator = (
        len(lanes) == _REQUIRED_MARKET_COUNT
        and represented_count == _REQUIRED_MARKET_COUNT
    )
    freshness_valid = bool(
        complete_denominator
        and all(item.get("freshness_valid") is True for item in lanes)
    )
    point_in_time_valid = bool(
        complete_denominator
        and all(item.get("point_in_time_valid") is True for item in lanes)
    )
    terminal_accounting_valid = bool(
        complete_denominator
        and all(item.get("terminal_accounting_complete") is True for item in lanes)
    )

    v2_available = resolved_audit.get("all_market_certification_v2_available") is True
    input_integrity = (
        resolved_audit.get("all_market_certification_v2_input_integrity_valid") is True
    )
    state_integrity = (
        resolved_audit.get("all_market_certification_v2_state_integrity_valid") is True
    )
    v2_release_matches = (
        resolved_audit.get("all_market_certification_v2_release_matches") is True
    )
    lane_integrity = (
        resolved_audit.get("all_market_certification_integrity_valid") is True
    )
    lane_release_matches = (
        resolved_audit.get("all_market_certification_release_matches") is True
    )
    runtime_certified = resolved_audit.get("all_market_runtime_certified") is True
    operational_certified = (
        resolved_audit.get("all_market_operational_certified") is True
    )
    state = _identity(resolved_audit.get("all_market_certification_v2_state"))

    integrity_valid = bool(
        input_integrity
        and state_integrity
        and lane_integrity
        and v2_release_matches
        and lane_release_matches
    )
    certified = bool(
        v2_available
        and integrity_valid
        and runtime_certified
        and operational_certified
        and state == "CERTIFIED"
        and complete_denominator
        and freshness_valid
        and point_in_time_valid
        and terminal_accounting_valid
    )

    if not v2_available:
        blocker = "certification_v2_unavailable"
    elif not (v2_release_matches and lane_release_matches):
        blocker = "release_mismatch"
    elif not (input_integrity and state_integrity and lane_integrity):
        blocker = "integrity_invalid"
    elif not complete_denominator:
        blocker = f"market_coverage:{represented_count}/{_REQUIRED_MARKET_COUNT}"
    elif not freshness_valid:
        blocker = "freshness_invalid"
    elif not point_in_time_valid:
        blocker = "point_in_time_invalid"
    elif not terminal_accounting_valid:
        blocker = "terminal_accounting_incomplete"
    elif not runtime_certified:
        blocker = "runtime_certification_incomplete"
    elif not operational_certified or state != "CERTIFIED":
        blocker = f"state:{state or 'unavailable'}"
    else:
        blocker = None

    certification_id = _identity(
        resolved_audit.get("all_market_certification_v2_id")
        or resolved_audit.get("all_market_certification_id")
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "certified": certified,
        "blocker": blocker,
        "release_sha": _release(resolved_values),
        "certification_id": certification_id,
        "certification_state": state,
        "evidence_cutoff": _identity(resolved_audit.get("certification_v2_cutoff")),
        "verifier_source_id": _identity(verifier_source_id),
        "coverage": {
            "certified_count": represented_count if certified else 0,
            "represented_count": represented_count,
            "required_count": _REQUIRED_MARKET_COUNT,
            "complete": complete_denominator,
        },
        "freshness_valid": freshness_valid,
        "point_in_time_valid": point_in_time_valid,
        "terminal_accounting_valid": terminal_accounting_valid,
        "integrity_valid": integrity_valid,
        "runtime_certified": runtime_certified,
        "operational_certified": operational_certified,
        "evidence_identity": {
            "evidence_generation_id": _identity(
                resolved_audit.get("all_market_evidence_generation_id")
            ),
            "point_in_time_snapshot_id": _identity(
                resolved_audit.get("all_market_point_in_time_snapshot_id")
            ),
            "global_discovery_snapshot_id": _identity(
                resolved_audit.get("all_market_global_discovery_snapshot_id")
            ),
            "us_equity_discovery_snapshot_id": _identity(
                resolved_audit.get("all_market_us_equity_discovery_snapshot_id")
            ),
            "paper_evidence_snapshot_id": _identity(
                resolved_audit.get("all_market_paper_evidence_snapshot_id")
            ),
            "policy_compatibility_hash": _identity(
                resolved_audit.get("all_market_policy_compatibility_hash")
            ),
            "aggregate_sha256": _identity(
                resolved_audit.get("all_market_certification_aggregate_sha256")
            ),
            "discovery_manifest_fingerprint": _identity(
                resolved_audit.get(
                    "all_market_certification_discovery_manifest_fingerprint"
                )
            ),
        },
        "source": "all-market-certification-v2-readonly",
        "paper_only": True,
        "real_money_authorized": False,
    }


def load_all_market_certification_envelope(
    *, values: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Load current-release immutable certification provenance without advancement authority."""

    resolved = dict(os.environ if values is None else values)
    verifier_source_id: str | None = None
    try:
        audit = public_all_market_certification_readonly(resolved)
    except (CertificationRuntimeStateError, OSError, TypeError, ValueError):
        audit = {}
    try:
        binding = resolve_latest_certification_readonly(values=resolved)
    except (CertificationRuntimeStateError, OSError, TypeError, ValueError):
        binding = None
    if binding is not None:
        verifier_source_id = binding.current_source_id
    return build_all_market_certification_envelope(
        audit,
        values=resolved,
        verifier_source_id=verifier_source_id,
    )


__all__ = [
    "build_all_market_certification_envelope",
    "load_all_market_certification_envelope",
]
