"""Credential-safe per-lane timing telemetry for comprehensive discovery.

This module persists operational timing only. The state cannot certify evidence, create or
qualify candidates, influence screening, authorize CIO decisions, size or construct a
portfolio, or authorize execution. It is deliberately independent of watchdog progress:
rewriting this file never advances the parent progress token or extends evidence freshness.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = "comprehensive-discovery-lane-telemetry.v1"
_STATE_FILENAME = "comprehensive-discovery-lane-telemetry.json"
_TIMESTAMP_FIELDS = (
    "lane_started_at",
    "structural_started_at",
    "structural_completed_at",
    "publication_started_at",
    "publication_completed_at",
    "screening_started_at",
    "screening_completed_at",
    "lane_completed_at",
    "lane_failed_at",
)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _state_path(values: Mapping[str, str]) -> Path | None:
    root = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not root:
        return None
    return Path(root).expanduser() / _STATE_FILENAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed(start: object, end: object) -> float | None:
    started = _parse_timestamp(start)
    completed = _parse_timestamp(end)
    if started is None or completed is None or completed < started:
        return None
    return round((completed - started).total_seconds(), 3)


def _authority_fields() -> dict[str, bool]:
    return {
        "credential_safe": True,
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "watchdog_progress_authority": False,
    }


def _request_identity(request_path: Path) -> tuple[str, str]:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("comprehensive request must be a mapping")
    request_id = str(payload.get("request_id") or "").strip()
    decision_epoch = str(payload.get("decision_epoch") or "").strip()
    if not request_id or _parse_timestamp(decision_epoch) is None:
        raise ValueError("comprehensive request telemetry identity is incomplete")
    return request_id, decision_epoch


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _recalculate(entry: dict[str, Any]) -> None:
    entry["structural_elapsed_seconds"] = _elapsed(
        entry.get("structural_started_at"), entry.get("structural_completed_at")
    )
    entry["publication_elapsed_seconds"] = _elapsed(
        entry.get("publication_started_at"), entry.get("publication_completed_at")
    )
    entry["screening_elapsed_seconds"] = _elapsed(
        entry.get("screening_started_at"), entry.get("screening_completed_at")
    )
    terminal = entry.get("lane_completed_at") or entry.get("lane_failed_at")
    entry["total_elapsed_seconds"] = _elapsed(entry.get("lane_started_at"), terminal)
    if entry.get("structural_cache_hit") is True:
        post_hit_end = (
            entry.get("lane_completed_at")
            or entry.get("screening_completed_at")
            or entry.get("publication_completed_at")
        )
        entry["post_hit_elapsed_seconds"] = _elapsed(
            entry.get("structural_completed_at"), post_hit_end
        )
    else:
        entry["post_hit_elapsed_seconds"] = None


def record_lane_phase(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class: str,
    index: int,
    **updates: object,
) -> None:
    """Persist one genuine lane transition without granting progress or evidence authority."""

    path = _state_path(values)
    if path is None:
        return
    request = Path(request_path).expanduser()
    request_id, decision_epoch = _request_identity(request)
    release = _release(values)
    if release == "unknown":
        return
    normalized_asset = str(asset_class or "").strip().lower()
    if not normalized_asset or isinstance(index, bool) or int(index) < 0:
        raise ValueError("lane telemetry identity is invalid")

    allowed = set(_TIMESTAMP_FIELDS) | {"structural_cache_hit", "error_type"}
    unexpected = set(updates).difference(allowed)
    if unexpected:
        raise ValueError("unsupported lane telemetry field")

    state = _load_state(path)
    if (
        state.get("schema_version") != _SCHEMA_VERSION
        or str(state.get("request_id") or "") != request_id
        or str(state.get("release") or "") != release
        or str(state.get("decision_epoch") or "") != decision_epoch
    ):
        state = {
            "schema_version": _SCHEMA_VERSION,
            "request_id": request_id,
            "release": release,
            "decision_epoch": decision_epoch,
            "lanes": {},
            **_authority_fields(),
        }

    lanes = state.get("lanes")
    if not isinstance(lanes, dict):
        lanes = {}
        state["lanes"] = lanes
    entry_raw = lanes.get(normalized_asset)
    entry = dict(entry_raw) if isinstance(entry_raw, Mapping) else {}
    if entry and int(entry.get("index", -1)) != int(index):
        raise ValueError("lane telemetry index changed inside one request")
    entry.update({"asset_class": normalized_asset, "index": int(index)})

    for name, value in updates.items():
        if name in _TIMESTAMP_FIELDS:
            if _parse_timestamp(value) is None:
                raise ValueError("lane telemetry timestamp is invalid")
            entry[name] = str(value)
        elif name == "structural_cache_hit":
            if value not in (True, False, None):
                raise ValueError("structural_cache_hit must be boolean or null")
            entry[name] = value
        elif name == "error_type":
            entry[name] = str(value or "")[:120] or None

    entry["updated_at"] = _utc_now()
    _recalculate(entry)
    lanes[normalized_asset] = entry
    state["updated_at"] = entry["updated_at"]
    _atomic_json(path, state)


def load_public_lane_telemetry(
    values: Mapping[str, str] | None = None,
) -> dict[str, object] | None:
    """Return only validated, credential-safe operational timing for the active release."""

    resolved = os.environ if values is None else values
    path = _state_path(resolved)
    if path is None:
        return None
    state = _load_state(path)
    release = _release(resolved)
    if (
        state.get("schema_version") != _SCHEMA_VERSION
        or str(state.get("release") or "") != release
        or state.get("credential_safe") is not True
        or state.get("advisory_only") is not True
        or state.get("paper_only") is not True
        or state.get("real_money_authorized") is not False
        or state.get("watchdog_progress_authority") is not False
    ):
        return None
    for authority in (
        "evidence_certified",
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if state.get(authority) is not False:
            return None

    lanes_raw = state.get("lanes")
    if not isinstance(lanes_raw, Mapping):
        return None
    lanes: list[dict[str, object]] = []
    for raw in lanes_raw.values():
        if not isinstance(raw, Mapping):
            continue
        asset = str(raw.get("asset_class") or "").strip().lower()
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        if not asset or index < 0:
            continue
        item: dict[str, object] = {
            "asset_class": asset,
            "index": index,
            "structural_cache_hit": raw.get("structural_cache_hit")
            if raw.get("structural_cache_hit") in (True, False)
            else None,
            "error_type": str(raw.get("error_type") or "")[:120] or None,
        }
        for field in _TIMESTAMP_FIELDS:
            value = raw.get(field)
            item[field] = str(value) if _parse_timestamp(value) is not None else None
        for field in (
            "structural_elapsed_seconds",
            "publication_elapsed_seconds",
            "screening_elapsed_seconds",
            "total_elapsed_seconds",
            "post_hit_elapsed_seconds",
        ):
            value = raw.get(field)
            item[field] = round(float(value), 3) if isinstance(value, (int, float)) else None
        lanes.append(item)
    lanes.sort(key=lambda item: int(item["index"]))

    hits = sum(item["structural_cache_hit"] is True for item in lanes)
    misses = sum(item["structural_cache_hit"] is False for item in lanes)
    unknown = len(lanes) - hits - misses
    slowest: dict[str, object] | None = None
    for item in lanes:
        for phase, field in (
            ("structure", "structural_elapsed_seconds"),
            ("publication", "publication_elapsed_seconds"),
            ("screening", "screening_elapsed_seconds"),
        ):
            seconds = item.get(field)
            if not isinstance(seconds, (int, float)):
                continue
            if slowest is None or float(seconds) > float(slowest["seconds"]):
                slowest = {
                    "asset_class": item["asset_class"],
                    "phase": phase,
                    "seconds": round(float(seconds), 3),
                }

    return {
        "schema_version": _SCHEMA_VERSION,
        "request_id": str(state.get("request_id") or "") or None,
        "release": release,
        "decision_epoch": str(state.get("decision_epoch") or "") or None,
        "updated_at": str(state.get("updated_at") or "") or None,
        "structural_cache_hits": hits,
        "structural_cache_misses": misses,
        "structural_cache_unknown": unknown,
        "slowest_completed_phase": slowest,
        "lanes": lanes,
        **_authority_fields(),
    }


__all__ = ["load_public_lane_telemetry", "record_lane_phase"]
