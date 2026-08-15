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
import re
from collections.abc import Mapping
from pathlib import Path

from operations.certification_runtime_state import (
    CertificationRuntimeBinding,
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


def _safe(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


def _root(values: Mapping[str, str]) -> Path:
    return Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser() / (
        "all-market-certification"
    )


def _v2_root(values: Mapping[str, str]) -> Path:
    return Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser() / (
        "all-market-certification-v2"
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


def _integrity_object(path: Path) -> Mapping[str, object] | None:
    payload = _load_object(path)
    if payload is None:
        return None
    body = dict(payload)
    integrity = body.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(body):
        return None
    return body


def _v2_input_integrity_valid(
    values: Mapping[str, str],
    binding: CertificationRuntimeBinding,
) -> bool:
    path = (
        _v2_root(values)
        / "inputs"
        / _safe(binding.release)
        / f"{binding.certification_id}.json"
    )
    payload = _load_object(path)
    if payload is None:
        return False
    record_id = str(payload.get("record_id") or "").strip()
    body = {str(key): value for key, value in payload.items() if key != "record_id"}
    return bool(
        record_id == binding.certification_id
        and _digest(body) == binding.certification_id
        and str(payload.get("schema_version") or "")
        == "all-market-certification-input.v2"
        and str(payload.get("release") or "") == binding.release
        and str(payload.get("snapshot_cutoff") or "") == binding.cutoff.isoformat()
        and str(payload.get("evidence_generation_id") or "")
        == binding.evidence_generation_id
        and str(payload.get("snapshot_id") or "") == binding.snapshot_id
        and str(payload.get("global_discovery_snapshot_id") or "")
        == binding.global_discovery_snapshot_id
        and str(payload.get("us_equity_discovery_snapshot_id") or "")
        == binding.us_equity_discovery_snapshot_id
        and str(payload.get("paper_evidence_snapshot_id") or "")
        == binding.paper_evidence_snapshot_id
        and str(payload.get("policy_compatibility_hash") or "")
        == binding.policy_compatibility_hash
        and payload.get("consumer_provider_refresh_permitted") is False
        and payload.get("paper_only") is True
        and payload.get("real_money_authorized") is False
    )


def _v2_state_integrity(
    values: Mapping[str, str],
    binding: CertificationRuntimeBinding,
) -> tuple[bool, CertificationState | None]:
    state_root = _v2_root(values) / "state" / binding.certification_id
    pointer = _integrity_object(state_root / "latest.json")
    if pointer is None:
        return False, None
    filename = str(pointer.get("event_filename") or "").strip()
    event_sha = str(pointer.get("event_sha256") or "").strip()
    if not filename or not event_sha:
        return False, None
    event = _load_object(state_root / "events" / filename)
    if event is None:
        return False, None
    embedded_sha = str(event.get("event_sha256") or "").strip()
    event_body = {str(key): value for key, value in event.items() if key != "event_sha256"}
    if not (
        embedded_sha
        and embedded_sha == event_sha
        and embedded_sha == _digest(event_body)
        and str(event.get("certification_id") or "") == binding.certification_id
        and str(event.get("state") or "") == binding.current_state.value
        and str(event.get("source_id") or "") == binding.current_source_id
        and pointer.get("paper_only") is True
        and pointer.get("real_money_authorized") is False
        and event.get("paper_only") is True
        and event.get("real_money_authorized") is False
    ):
        return False, None

    terminal: CertificationState | None = None
    if binding.current_state in {
        CertificationState.PAPER_IMPLEMENTED,
        CertificationState.NO_ACTION,
    }:
        terminal = binding.current_state
    elif binding.current_state is CertificationState.CERTIFIED:
        try:
            previous = CertificationState(str(event.get("previous_state") or ""))
        except ValueError:
            return False, None
        if previous not in {
            CertificationState.PAPER_IMPLEMENTED,
            CertificationState.NO_ACTION,
        }:
            return False, None
        terminal = previous
    return True, terminal


def _state_reached(current: CertificationState, target: CertificationState) -> bool:
    order = (
        CertificationState.EVIDENCE_READY,
        CertificationState.SNAPSHOT_FROZEN,
        CertificationState.SCREENING_COMPLETE,
        CertificationState.COMMITTEE_COMPLETE,
        CertificationState.CIO_COMPLETE,
        CertificationState.CONSTRUCTION_COMPLETE,
    )
    rank = {state: index for index, state in enumerate(order)}
    target_rank = rank[target]
    current_rank = rank.get(current)
    if current_rank is not None:
        return current_rank >= target_rank
    return current in {
        CertificationState.PAPER_IMPLEMENTED,
        CertificationState.NO_ACTION,
        CertificationState.CERTIFIED,
    }


def _runtime_v2_audit(values: Mapping[str, str]) -> dict[str, object]:
    enabled = certification_runtime_enabled(values)
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
        # Backward-compatible raw v2 names remain available during migration.
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
        "certification_v2_enabled": True,
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
