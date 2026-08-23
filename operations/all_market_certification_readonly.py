"""Read-only bridge from independently produced all-market certification to web audit.

The Render capability-scoped operating process must not advance exhaustive certification,
but it may verify immutable certification artifacts produced by the independent certification
runtime.  This module deliberately contains no state-transition, provider-refresh, portfolio,
or execution authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from operations.all_market_certification_audit import (
    _state_reached,
    _v2_input_integrity_valid,
    _v2_state_integrity,
    public_all_market_certification,
)
from operations.all_market_lane_certification import (
    AllMarketLaneCertificationError,
    evaluate_lane_artifacts,
)
from operations.certification_runtime_state import (
    CertificationRuntimeBinding,
    CertificationRuntimeStateError,
    resolve_certification_for_cutoff,
)
from operations.certification_state_machine import CertificationState


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _safe(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


def _data_root(values: Mapping[str, str]) -> Path:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not raw:
        raise CertificationRuntimeStateError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for certification audit reads"
        )
    return Path(raw).expanduser()


def _load_mapping(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _integrity_mapping(path: Path) -> Mapping[str, object] | None:
    payload = _load_mapping(path)
    if payload is None:
        return None
    body = dict(payload)
    integrity = body.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(body):
        return None
    return body


def resolve_latest_certification_readonly(
    *, values: Mapping[str, str]
) -> CertificationRuntimeBinding:
    """Resolve latest certification without acquiring advancement authority.

    Unlike ``resolve_latest_certification`` this reader intentionally does not consult
    ``certification_runtime_enabled``.  It reads the integrity-protected latest-input
    pointer, then delegates to the exact-cutoff resolver, which is itself read-only.
    """

    release = _release(values)
    if release == "unknown":
        raise CertificationRuntimeStateError("certification release is unavailable")
    latest = _integrity_mapping(
        _data_root(values)
        / "all-market-certification-v2"
        / "ledger"
        / _safe(release)
        / "latest-input.json"
    )
    if latest is None:
        raise CertificationRuntimeStateError("certification input ledger is unavailable")
    if str(latest.get("release") or "") != release:
        raise CertificationRuntimeStateError("certification input release mismatch")
    raw_cutoff = latest.get("snapshot_cutoff")
    if not isinstance(raw_cutoff, str):
        raise CertificationRuntimeStateError("certification input cutoff is missing")
    try:
        cutoff = datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00"))
    except ValueError as error:
        raise CertificationRuntimeStateError("certification input cutoff is invalid") from error
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise CertificationRuntimeStateError("certification input cutoff is not timezone-aware")
    return resolve_certification_for_cutoff(
        cutoff.astimezone(timezone.utc),
        values=values,
    )


def _readonly_v2(values: Mapping[str, str]) -> dict[str, object]:
    unavailable = {
        "all_market_certification_v2_available": False,
        "all_market_certification_v2_input_integrity_valid": False,
        "all_market_certification_v2_state_integrity_valid": False,
        "all_market_certification_v2_release_matches": False,
        "all_market_certification_v2_id": None,
        "all_market_evidence_generation_id": None,
        "all_market_point_in_time_snapshot_id": None,
        "all_market_global_discovery_snapshot_id": None,
        "all_market_us_equity_discovery_snapshot_id": None,
        "all_market_paper_evidence_snapshot_id": None,
        "all_market_policy_compatibility_hash": None,
        "all_market_certification_v2_state": None,
        "all_market_evidence_certified": False,
        "all_market_screening_certified": False,
        "all_market_committee_certified": False,
        "all_market_cio_certified": False,
        "all_market_construction_certified": False,
        "all_market_paper_implementation_certified": False,
        "all_market_no_action_certified": False,
        "all_market_operational_certified": False,
        "certification_v2_readable": False,
        "certification_v2_blocker": "runtime_state_unavailable",
    }
    try:
        binding = resolve_latest_certification_readonly(values=values)
    except CertificationRuntimeStateError as error:
        return {**unavailable, "certification_v2_blocker": f"runtime_state_unavailable:{error}"}

    input_integrity = _v2_input_integrity_valid(values, binding)
    state_integrity, terminal = _v2_state_integrity(values, binding)
    release_matches = binding.release == _release(values) and binding.release != "unknown"
    trustworthy = input_integrity and state_integrity and release_matches
    evidence = trustworthy and _state_reached(binding.current_state, CertificationState.SNAPSHOT_FROZEN)
    screening = trustworthy and _state_reached(binding.current_state, CertificationState.SCREENING_COMPLETE)
    committee = trustworthy and _state_reached(binding.current_state, CertificationState.COMMITTEE_COMPLETE)
    cio = trustworthy and _state_reached(binding.current_state, CertificationState.CIO_COMPLETE)
    construction = trustworthy and _state_reached(binding.current_state, CertificationState.CONSTRUCTION_COMPLETE)
    paper_implemented = trustworthy and terminal is CertificationState.PAPER_IMPLEMENTED
    no_action = trustworthy and terminal is CertificationState.NO_ACTION
    operational = trustworthy and binding.current_state is CertificationState.CERTIFIED
    return {
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": input_integrity,
        "all_market_certification_v2_state_integrity_valid": state_integrity,
        "all_market_certification_v2_release_matches": release_matches,
        "all_market_certification_v2_id": binding.certification_id,
        "all_market_evidence_generation_id": binding.evidence_generation_id,
        "all_market_point_in_time_snapshot_id": binding.snapshot_id,
        "all_market_global_discovery_snapshot_id": binding.global_discovery_snapshot_id or None,
        "all_market_us_equity_discovery_snapshot_id": binding.us_equity_discovery_snapshot_id or None,
        "all_market_paper_evidence_snapshot_id": binding.paper_evidence_snapshot_id or None,
        "all_market_policy_compatibility_hash": binding.policy_compatibility_hash or None,
        "all_market_certification_v2_state": binding.current_state.value,
        "all_market_evidence_certified": evidence,
        "all_market_screening_certified": screening,
        "all_market_committee_certified": committee,
        "all_market_cio_certified": cio,
        "all_market_construction_certified": construction,
        "all_market_paper_implementation_certified": paper_implemented,
        "all_market_no_action_certified": no_action,
        "all_market_operational_certified": operational,
        "certification_v2_readable": True,
        "certification_v2_id": binding.certification_id,
        "certification_v2_state": binding.current_state.value,
        "certification_v2_cutoff": binding.cutoff.isoformat(),
        "certification_v2_evidence_generation_id": binding.evidence_generation_id,
        "certification_v2_snapshot_id": binding.snapshot_id,
        "certification_v2_global_discovery_snapshot_id": binding.global_discovery_snapshot_id or None,
        "certification_v2_us_equity_discovery_snapshot_id": binding.us_equity_discovery_snapshot_id or None,
        "certification_v2_paper_evidence_snapshot_id": binding.paper_evidence_snapshot_id or None,
        "certification_v2_policy_compatibility_hash": binding.policy_compatibility_hash or None,
        "certification_v2_blocker": None if operational else f"state:{binding.current_state.value}",
    }


def _legacy_lane_audit(values: Mapping[str, str]) -> dict[str, object]:
    unavailable = {
        "all_market_comprehensive_discovery_complete": False,
        "all_market_scheduled_market_coverage_complete": False,
        "all_market_terminal_screening_complete": False,
        "all_market_certified_lanes": [],
    }
    root = _data_root(values) / "all-market-certification"
    latest = _load_mapping(root / "latest.json")
    if latest is None:
        return unavailable
    certification_id = str(latest.get("certification_id") or "").strip()
    release = _release(values)
    if not certification_id or str(latest.get("release_sha") or "") != release:
        return unavailable
    certification_dir = root / "certifications" / certification_id
    manifest = _load_mapping(certification_dir / "manifest.json")
    if manifest is None:
        return unavailable
    required = manifest.get("required_lanes")
    if not isinstance(required, list) or not required:
        return unavailable

    artifacts: dict[str, Mapping[str, object]] = {}
    lanes: list[dict[str, object]] = []
    for raw_lane in required:
        lane = str(raw_lane)
        pointer = _load_mapping(certification_dir / "lanes" / lane / "current.json")
        if pointer is None:
            return unavailable
        artifact_name = str(pointer.get("artifact_path") or "").strip()
        if not artifact_name or "/" in artifact_name or "\\" in artifact_name:
            return unavailable
        artifact = _load_mapping(certification_dir / "lanes" / lane / artifact_name)
        if artifact is None:
            return unavailable
        body = {str(key): value for key, value in artifact.items() if key != "artifact_sha256"}
        if str(artifact.get("artifact_sha256") or "") != _digest(body):
            return unavailable
        artifacts[lane] = artifact
        lanes.append(
            {
                "asset_class": lane,
                "scheduled": True,
                "catalog_count": int(artifact.get("catalog_count") or 0),
                "deep_analyzed_count": int(artifact.get("deep_analyzed_count") or 0),
                "selected_count": int(artifact.get("selected_count") or 0),
                "excluded_count": int(artifact.get("excluded_count") or 0),
                "terminal_count": int(artifact.get("terminal_count") or 0),
                "represented": int(artifact.get("catalog_count") or 0) > 0,
                "terminal_accounting_complete": artifact.get("terminal_accounting_complete") is True,
                "point_in_time_valid": artifact.get("point_in_time_valid") is True,
                "freshness_valid": artifact.get("freshness_valid") is True,
            }
        )
    try:
        evaluated = evaluate_lane_artifacts(manifest, artifacts)
    except AllMarketLaneCertificationError:
        return unavailable
    complete = evaluated.get("all_market_runtime_certified") is True
    represented = complete and bool(lanes) and all(item["represented"] is True for item in lanes)
    terminal = complete and all(item["terminal_accounting_complete"] is True for item in lanes)
    return {
        "all_market_comprehensive_discovery_complete": complete,
        "all_market_scheduled_market_coverage_complete": represented,
        "all_market_terminal_screening_complete": terminal,
        "all_market_certified_lanes": lanes,
    }


def public_all_market_certification_readonly(values: Mapping[str, str]) -> dict[str, object]:
    """Return the public audit with independent certification readable but never advanced."""

    base = public_all_market_certification(values)
    v2 = _readonly_v2(values)
    lanes = _legacy_lane_audit(values)
    # V2 runtime mutation may legitimately be disabled in the web process.  The immutable
    # read result is authoritative for audit fields; the legacy ``certification_v2_enabled``
    # field remains untouched so callers can still see that advancement authority is absent.
    return {**base, **v2, **lanes}


__all__ = [
    "public_all_market_certification_readonly",
    "resolve_latest_certification_readonly",
]
