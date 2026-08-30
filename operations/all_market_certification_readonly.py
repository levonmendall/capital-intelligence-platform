"""Read-only bridge from independently produced all-market certification to web audit.

The Render capability-scoped operating process must not advance exhaustive certification,
but it may verify immutable certification artifacts produced by the independent certification
runtime. This module deliberately contains no state-transition, provider-refresh, portfolio,
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
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    load_qualified_comprehensive_discovery_snapshot,
)


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


def _v2_root(values: Mapping[str, str]) -> Path:
    return _data_root(values) / "all-market-certification-v2"


def _v2_latest_ledger_path(values: Mapping[str, str]) -> Path:
    return (
        _v2_root(values)
        / "ledger"
        / _safe(_release(values))
        / "latest-input.json"
    )


def _legacy_root(values: Mapping[str, str]) -> Path:
    return (
        Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser()
        / "all-market-certification"
    )


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


def _aware_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def resolve_latest_certification_readonly(
    *, values: Mapping[str, str]
) -> CertificationRuntimeBinding:
    """Resolve latest certification without acquiring advancement authority."""

    release = _release(values)
    if release == "unknown":
        raise CertificationRuntimeStateError("certification release is unavailable")
    latest = _integrity_mapping(_v2_latest_ledger_path(values))
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
        cutoff.astimezone(timezone.utc), values=values
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
        return {
            **unavailable,
            "certification_v2_blocker": f"runtime_state_unavailable:{error}",
        }

    input_integrity = _v2_input_integrity_valid(values, binding)
    state_integrity, terminal = _v2_state_integrity(values, binding)
    release_matches = binding.release == _release(values) and binding.release != "unknown"
    trustworthy = input_integrity and state_integrity and release_matches
    evidence = trustworthy and _state_reached(
        binding.current_state, CertificationState.SNAPSHOT_FROZEN
    )
    screening = trustworthy and _state_reached(
        binding.current_state, CertificationState.SCREENING_COMPLETE
    )
    committee = trustworthy and _state_reached(
        binding.current_state, CertificationState.COMMITTEE_COMPLETE
    )
    cio = trustworthy and _state_reached(
        binding.current_state, CertificationState.CIO_COMPLETE
    )
    construction = trustworthy and _state_reached(
        binding.current_state, CertificationState.CONSTRUCTION_COMPLETE
    )
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
        "certification_v2_blocker": (
            None if operational else f"state:{binding.current_state.value}"
        ),
    }


def _unavailable_v2_lane_audit() -> dict[str, object]:
    """Return a fail-closed projection for an authoritative but unproved v2 ledger."""

    return {
        "all_market_runtime_certified": False,
        "all_market_certification_integrity_valid": False,
        "all_market_certification_release_matches": False,
        "all_market_certification_id": None,
        "all_market_certification_epoch": None,
        "all_market_certification_aggregate_sha256": None,
        "all_market_certification_discovery_manifest_fingerprint": None,
        "all_market_comprehensive_discovery_complete": False,
        "all_market_scheduled_market_coverage_complete": False,
        "all_market_terminal_screening_complete": False,
        "all_market_certified_lanes": [],
        "all_market_lane_certification_source": "certification_v2_global_snapshot",
    }


def _v2_lane_audit(
    values: Mapping[str, str],
    v2: Mapping[str, object],
) -> dict[str, object]:
    """Reconstruct lane proof from the immutable v2 global-discovery snapshot.

    Certification v2 freezes the exact qualified global snapshot and the scheduled-lane
    set into a content-addressed input record. Once screening reaches its durable v2 state,
    those artifacts are sufficient to reproduce the legacy lane terminal-accounting checks
    without requiring a second mutable ``all-market-certification/latest.json`` pointer.
    """

    unavailable = _unavailable_v2_lane_audit()
    if not all(
        (
            v2.get("all_market_certification_v2_available") is True,
            v2.get("all_market_certification_v2_input_integrity_valid") is True,
            v2.get("all_market_certification_v2_state_integrity_valid") is True,
            v2.get("all_market_certification_v2_release_matches") is True,
            v2.get("all_market_evidence_certified") is True,
            v2.get("all_market_screening_certified") is True,
        )
    ):
        return unavailable

    certification_id = str(v2.get("all_market_certification_v2_id") or "").strip()
    release = _release(values)
    if not certification_id or release == "unknown":
        return unavailable
    input_path = (
        _v2_root(values)
        / "inputs"
        / _safe(release)
        / f"{certification_id}.json"
    )
    input_payload = _load_mapping(input_path)
    if input_payload is None:
        return unavailable
    record_id = str(input_payload.get("record_id") or "").strip()
    input_body = {
        str(key): value
        for key, value in input_payload.items()
        if key != "record_id"
    }
    if not (
        record_id == certification_id
        and _digest(input_body) == certification_id
        and str(input_payload.get("schema_version") or "")
        == "all-market-certification-input.v2"
        and str(input_payload.get("release") or "") == release
        and str(input_payload.get("global_discovery_snapshot_id") or "")
        == str(v2.get("all_market_global_discovery_snapshot_id") or "")
    ):
        return unavailable

    evidence_as_of = _aware_iso(input_payload.get("evidence_as_of"))
    raw_scheduled = input_payload.get("scheduled_lanes")
    if evidence_as_of is None or not isinstance(raw_scheduled, list) or not raw_scheduled:
        return unavailable
    scheduled_lanes = tuple(str(item).strip() for item in raw_scheduled)
    if any(not item for item in scheduled_lanes) or len(set(scheduled_lanes)) != len(
        scheduled_lanes
    ):
        return unavailable

    try:
        snapshot = load_qualified_comprehensive_discovery_snapshot(
            evidence_as_of=evidence_as_of,
            values=values,
        )
    except (ComprehensiveDiscoverySnapshotError, OSError, TypeError, ValueError):
        return unavailable
    if snapshot.snapshot_id != str(
        input_payload.get("global_discovery_snapshot_id") or ""
    ):
        return unavailable

    scheduled_snapshot_lanes = tuple(
        lane for lane in snapshot.result.lanes if bool(lane.scheduled)
    )
    snapshot_lane_names = tuple(lane.asset_class.value for lane in scheduled_snapshot_lanes)
    if (
        len(set(snapshot_lane_names)) != len(snapshot_lane_names)
        or set(snapshot_lane_names) != set(scheduled_lanes)
    ):
        return unavailable

    lanes: list[dict[str, object]] = []
    all_terminal = True
    all_point_in_time = True
    for lane in scheduled_snapshot_lanes:
        selected_count = len(lane.selected)
        excluded_count = len(lane.exclusions)
        terminal_count = selected_count + excluded_count
        catalog_count = int(lane.catalog_count)
        point_in_time_valid = all(
            item.features.observed_at.tzinfo is not None
            and item.features.observed_at.utcoffset() is not None
            and item.features.observed_at.astimezone(timezone.utc) <= evidence_as_of
            for item in lane.selected
        )
        terminal_accounting_complete = terminal_count == catalog_count
        all_terminal = all_terminal and terminal_accounting_complete
        all_point_in_time = all_point_in_time and point_in_time_valid
        lanes.append(
            {
                "asset_class": lane.asset_class.value,
                "scheduled": True,
                "catalog_count": catalog_count,
                "deep_analyzed_count": int(lane.deep_analyzed_count),
                "selected_count": selected_count,
                "excluded_count": excluded_count,
                "terminal_count": terminal_count,
                "represented": catalog_count > 0,
                "terminal_accounting_complete": terminal_accounting_complete,
                "point_in_time_valid": point_in_time_valid,
                "freshness_valid": point_in_time_valid,
            }
        )

    complete = bool(lanes) and all_terminal and all_point_in_time
    represented = complete and all(item["represented"] is True for item in lanes)
    terminal = complete and v2.get("all_market_screening_certified") is True
    return {
        "all_market_runtime_certified": complete,
        "all_market_certification_integrity_valid": complete,
        "all_market_certification_release_matches": True,
        "all_market_certification_id": certification_id,
        "all_market_certification_epoch": evidence_as_of.isoformat(),
        "all_market_certification_aggregate_sha256": None,
        "all_market_certification_discovery_manifest_fingerprint": (
            snapshot.result.manifest_fingerprint or None
        ),
        "all_market_comprehensive_discovery_complete": complete,
        "all_market_scheduled_market_coverage_complete": represented,
        "all_market_terminal_screening_complete": terminal,
        "all_market_certified_lanes": lanes,
        "all_market_lane_certification_source": "certification_v2_global_snapshot",
    }


def _legacy_lane_audit(values: Mapping[str, str]) -> dict[str, object]:
    unavailable = {
        "all_market_comprehensive_discovery_complete": False,
        "all_market_scheduled_market_coverage_complete": False,
        "all_market_terminal_screening_complete": False,
        "all_market_certified_lanes": [],
        "all_market_lane_certification_source": "legacy_compositional_certificate",
    }
    root = _legacy_root(values)
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
        body = {
            str(key): value
            for key, value in artifact.items()
            if key != "artifact_sha256"
        }
        if str(artifact.get("artifact_sha256") or "") != _digest(body):
            return unavailable
        artifacts[lane] = artifact
        lanes.append(
            {
                "asset_class": lane,
                "scheduled": True,
                "catalog_count": int(artifact.get("catalog_count") or 0),
                "deep_analyzed_count": int(
                    artifact.get("deep_analyzed_count") or 0
                ),
                "selected_count": int(artifact.get("selected_count") or 0),
                "excluded_count": int(artifact.get("excluded_count") or 0),
                "terminal_count": int(artifact.get("terminal_count") or 0),
                "represented": int(artifact.get("catalog_count") or 0) > 0,
                "terminal_accounting_complete": (
                    artifact.get("terminal_accounting_complete") is True
                ),
                "point_in_time_valid": artifact.get("point_in_time_valid") is True,
                "freshness_valid": artifact.get("freshness_valid") is True,
            }
        )
    try:
        evaluated = evaluate_lane_artifacts(manifest, artifacts)
    except AllMarketLaneCertificationError:
        return unavailable
    complete = evaluated.get("all_market_runtime_certified") is True
    represented = complete and bool(lanes) and all(
        item["represented"] is True for item in lanes
    )
    terminal = complete and all(
        item["terminal_accounting_complete"] is True for item in lanes
    )
    return {
        "all_market_comprehensive_discovery_complete": complete,
        "all_market_scheduled_market_coverage_complete": represented,
        "all_market_terminal_screening_complete": terminal,
        "all_market_certified_lanes": lanes,
        "all_market_lane_certification_source": "legacy_compositional_certificate",
    }


def public_all_market_certification_readonly(
    values: Mapping[str, str],
) -> dict[str, object]:
    """Return public audit with independent certification readable but never advanced.

    A current-release v2 ledger is authoritative once published. Its immutable qualified
    global snapshot supplies the lane proof; an incomplete/corrupt v2 handoff fails closed
    instead of silently falling back to an older mutable legacy pointer. Legacy lane
    certification remains readable only when no v2 ledger exists for the current release.
    """

    base = public_all_market_certification(values)
    v2 = _readonly_v2(values)
    if _v2_latest_ledger_path(values).exists():
        lanes = _v2_lane_audit(values, v2)
    else:
        lanes = _legacy_lane_audit(values)
    return {**base, **v2, **lanes}


__all__ = [
    "public_all_market_certification_readonly",
    "resolve_latest_certification_readonly",
]
