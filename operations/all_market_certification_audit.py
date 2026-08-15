"""Credential-safe reader for all-market certification evidence and runtime state.

The legacy compositional certificate remains exposed for backward-compatible evidence
verification. Certification v2 adds the immutable release/evidence/policy handoff and a
durable end-to-end operational state machine. This audit surface is strictly read-only:
it never advances certification, reruns evidence, or exercises investment/execution
authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from operations.certification_runtime_state import (
    CertificationRuntimeStateError,
    certification_runtime_enabled,
    resolve_latest_certification,
)
from operations.certification_state_machine import CertificationState


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _root(values: Mapping[str, str]) -> Path:
    return Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser() / (
        "all-market-certification"
    )


def _load_object(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _runtime_v2_audit(values: Mapping[str, str]) -> dict[str, object]:
    enabled = certification_runtime_enabled(values)
    unavailable = {
        "all_market_operational_certified": False,
        "certification_v2_enabled": enabled,
        "certification_v2_id": None,
        "certification_v2_state": None,
        "certification_v2_cutoff": None,
        "certification_v2_evidence_generation_id": None,
        "certification_v2_snapshot_id": None,
        "certification_v2_global_discovery_snapshot_id": None,
        "certification_v2_us_equity_discovery_snapshot_id": None,
        "certification_v2_paper_evidence_snapshot_id": None,
        "certification_v2_policy_compatibility_hash": None,
        "certification_v2_blocker": (
            None if enabled else "certification_v2_disabled"
        ),
    }
    if not enabled:
        return unavailable
    try:
        binding = resolve_latest_certification(values=values)
    except CertificationRuntimeStateError as error:
        return {
            **unavailable,
            "certification_v2_blocker": f"runtime_state_unavailable:{error}",
        }
    if binding is None:
        return {
            **unavailable,
            "certification_v2_blocker": "runtime_state_unavailable",
        }
    operational = binding.current_state is CertificationState.CERTIFIED
    return {
        "all_market_operational_certified": operational,
        "certification_v2_enabled": True,
        "certification_v2_id": binding.certification_id,
        "certification_v2_state": binding.current_state.value,
        "certification_v2_cutoff": binding.cutoff.isoformat(),
        "certification_v2_evidence_generation_id": binding.evidence_generation_id,
        "certification_v2_snapshot_id": binding.snapshot_id,
        "certification_v2_global_discovery_snapshot_id": (
            binding.global_discovery_snapshot_id or None
        ),
        "certification_v2_us_equity_discovery_snapshot_id": (
            binding.us_equity_discovery_snapshot_id or None
        ),
        "certification_v2_paper_evidence_snapshot_id": (
            binding.paper_evidence_snapshot_id or None
        ),
        "certification_v2_policy_compatibility_hash": (
            binding.policy_compatibility_hash or None
        ),
        "certification_v2_blocker": (
            None
            if operational
            else f"state:{binding.current_state.value}"
        ),
    }


def public_all_market_certification(
    values: Mapping[str, str],
) -> dict[str, object]:
    """Return redacted evidence integrity plus durable operational certification state."""

    release = _release(values)
    v2 = _runtime_v2_audit(values)
    unavailable = {
        "all_market_runtime_certified": False,
        "all_market_certification_integrity_valid": False,
        "all_market_certification_release_matches": False,
        "all_market_certification_id": None,
        "all_market_certification_epoch": None,
        "all_market_certification_aggregate_sha256": None,
        "all_market_certification_discovery_manifest_fingerprint": None,
        **v2,
    }
    latest = _load_object(_root(values) / "latest.json")
    if latest is None:
        return unavailable

    certification_id = str(latest.get("certification_id") or "").strip()
    latest_release = str(latest.get("release_sha") or "").strip()
    aggregate_sha = str(latest.get("aggregate_sha256") or "").strip()
    decision_epoch = str(latest.get("decision_epoch") or "").strip()
    release_matches = bool(
        certification_id
        and latest_release == release
        and release != "unknown"
    )
    if not release_matches or not aggregate_sha:
        return {
            **unavailable,
            "all_market_certification_release_matches": release_matches,
            "all_market_certification_id": certification_id or None,
            "all_market_certification_epoch": decision_epoch or None,
            "all_market_certification_aggregate_sha256": aggregate_sha or None,
        }

    aggregate = _load_object(
        _root(values) / "certifications" / certification_id / "aggregate.json"
    )
    if aggregate is None:
        return {
            **unavailable,
            "all_market_certification_release_matches": True,
            "all_market_certification_id": certification_id,
            "all_market_certification_epoch": decision_epoch or None,
            "all_market_certification_aggregate_sha256": aggregate_sha,
        }

    body = {str(key): value for key, value in aggregate.items() if key != "sha256"}
    embedded_sha = str(aggregate.get("sha256") or "").strip()
    discovery_fingerprint = str(
        aggregate.get("discovery_manifest_fingerprint") or ""
    ).strip()
    integrity_valid = bool(
        embedded_sha
        and embedded_sha == aggregate_sha
        and embedded_sha == _digest(body)
        and str(aggregate.get("certification_id") or "") == certification_id
        and str(aggregate.get("release_sha") or "") == release
        and str(aggregate.get("decision_epoch") or "") == decision_epoch
        and discovery_fingerprint
    )
    certified = bool(
        integrity_valid and aggregate.get("all_market_runtime_certified") is True
    )
    return {
        "all_market_runtime_certified": certified,
        "all_market_certification_integrity_valid": integrity_valid,
        "all_market_certification_release_matches": True,
        "all_market_certification_id": certification_id,
        "all_market_certification_epoch": decision_epoch or None,
        "all_market_certification_aggregate_sha256": aggregate_sha,
        "all_market_certification_discovery_manifest_fingerprint": (
            discovery_fingerprint or None
        ),
        **v2,
    }


__all__ = ["public_all_market_certification"]
