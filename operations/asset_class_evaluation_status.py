"""Read-only asset-class evaluation status for the portfolio command center.

The dashboard needs a compact answer to two operational questions: how many asset
classes did comprehensive research try to evaluate, and which of those classes actually
completed terminal all-market evaluation. This module projects that answer from existing
durable artifacts only. It does not run discovery, contact providers, certify anything,
nominate candidates, or grant investment/execution authority.

Source precedence is intentionally fail-closed:
1. the newest exact-release certification-DAG attempt establishes the attempted lanes;
2. a matching all-market aggregate and its immutable lane artifacts establish per-lane
   terminal success, including partial success when the global barrier fails;
3. if there is no current exact-release attempt yet, the latest release-independent
   comprehensive snapshot supplies the most recent completed global evaluation view.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


_DAG_SCHEMA = "persistent-certification-manifest.v1"
_CERT_SCHEMA = "all-market-lane-certification.v1"
_SNAPSHOT_SCHEMA = "comprehensive-discovery-snapshot.v2"
_SNAPSHOT_POINTER_SCHEMA = "comprehensive-discovery-snapshot-pointer.v1"

_LABELS = {
    "us_equity": "U.S. equities",
    "us_etf": "U.S. ETFs",
    "cash_equivalent": "Cash equivalents",
    "fixed_income": "Fixed income",
    "international_equity": "International equities",
    "commodity": "Commodities",
    "fx": "FX",
    "crypto": "Crypto",
    "real_estate": "Real estate",
    "future": "Futures",
    "option": "Options",
    "volatility": "Volatility",
    "alternative": "Alternatives",
    "other": "Other",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _release(values: Mapping[str, str]) -> str:
    return str(
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _data_root(values: Mapping[str, str]) -> Path:
    return Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser()


def _label(lane: str) -> str:
    normalized = str(lane).strip().lower()
    return _LABELS.get(normalized, normalized.replace("_", " ").title())


def _lane_from_node(node_id: object) -> str | None:
    text = str(node_id or "").strip()
    prefix = "deep-market-evidence:"
    if not text.startswith(prefix):
        return None
    lane = text[len(prefix) :].strip().lower()
    return lane or None


def _summary(
    rows: list[dict[str, object]],
    *,
    as_of: object = None,
    source: str,
) -> dict[str, object]:
    return {
        "successful": sum(1 for row in rows if row.get("status") == "Evaluated"),
        "attempted": len(rows),
        "as_of": as_of,
        "source": source,
        "rows": rows,
    }


def _latest_dag_attempt(values: Mapping[str, str]) -> dict[str, object] | None:
    release_sha = _release(values)
    if not release_sha or release_sha == "unknown":
        return None
    base = (
        _data_root(values)
        / "certification-dag"
        / "persistent-certification-dag.v1"
        / release_sha
    )
    try:
        candidates = sorted(base.glob("*/latest.json"), reverse=True)
    except OSError:
        return None

    for path in candidates:
        payload = _read_mapping(path)
        if payload is None:
            continue
        body = payload.get("body")
        if not isinstance(body, Mapping) or payload.get("sha256") != _digest(body):
            continue
        if (
            body.get("schema_version") != _DAG_SCHEMA
            or body.get("release_sha") != release_sha
            or body.get("paper_only") is not True
            or body.get("real_money_authorized") is not False
        ):
            continue
        required = body.get("required_nodes")
        results = body.get("node_results")
        if not isinstance(required, list) or not isinstance(results, Mapping):
            continue

        rows: list[dict[str, object]] = []
        for node_id in required:
            lane = _lane_from_node(node_id)
            if lane is None:
                continue
            raw_result = results.get(str(node_id))
            item = raw_result if isinstance(raw_result, Mapping) else {}
            raw_status = str(item.get("status") or "pending").strip().lower()
            failure_type = str(item.get("failure_type") or "").strip()
            if raw_status == "failed":
                status = "Failed"
                detail = "Evaluation evidence failed"
                if failure_type:
                    detail += f" · {failure_type}"
            elif raw_status == "qualified":
                status = "In progress"
                detail = "Market evidence qualified · terminal evaluation pending"
                if item.get("reused") is True:
                    detail = "Exact-epoch market evidence reused · terminal evaluation pending"
            else:
                status = "In progress"
                detail = "Scheduled for the current comprehensive evaluation"
            rows.append(
                {
                    "key": lane,
                    "asset_class": _label(lane),
                    "status": status,
                    "detail": detail,
                }
            )
        if rows:
            return {
                "release_sha": release_sha,
                "decision_epoch": body.get("decision_epoch"),
                "rows": rows,
            }
    return None


def _artifact_row(
    directory: Path,
    *,
    lane: str,
    certification_id: str,
    release_sha: str,
    decision_epoch: object,
    blocking_reasons: tuple[str, ...],
) -> dict[str, object]:
    detail = "Terminal evaluation did not certify"
    status = "Failed"
    current = _read_mapping(directory / "lanes" / lane / "current.json")
    artifact: Mapping[str, Any] | None = None
    if current is not None:
        artifact_name = current.get("artifact_path")
        if (
            isinstance(artifact_name, str)
            and artifact_name
            and Path(artifact_name).name == artifact_name
        ):
            artifact = _read_mapping(directory / "lanes" / lane / artifact_name)

    valid = False
    if artifact is not None:
        body = {
            str(key): value
            for key, value in artifact.items()
            if key != "artifact_sha256"
        }
        exact_fields = {
            "schema_version": _CERT_SCHEMA,
            "certification_id": certification_id,
            "release_sha": release_sha,
            "lane": lane,
            "decision_epoch": decision_epoch,
            "evidence_effective_at": decision_epoch,
            "completion_status": "complete",
        }
        valid = (
            artifact.get("artifact_sha256") == _digest(body)
            and all(artifact.get(key) == value for key, value in exact_fields.items())
            and artifact.get("candidate_count_limit_applied") is False
            and artifact.get("terminal_accounting_complete") is True
            and artifact.get("point_in_time_valid") is True
            and artifact.get("freshness_valid") is True
            and isinstance(artifact.get("catalog_count"), int)
            and artifact.get("terminal_count") == artifact.get("catalog_count")
        )
        if valid:
            status = "Evaluated"
            catalog = artifact.get("catalog_count")
            deep = artifact.get("deep_analyzed_count")
            selected = artifact.get("selected_count")
            if all(
                isinstance(value, int) and value >= 0
                for value in (catalog, deep, selected)
            ):
                detail = (
                    f"{catalog} cataloged · {deep} deep analyzed · "
                    f"{selected} selected"
                )
            else:
                detail = "Terminal evaluation complete"

    if not valid:
        lane_reasons = [
            item.split(":", 1)[1].replace("_", " ")
            for item in blocking_reasons
            if item.startswith(f"{lane}:") and ":" in item
        ]
        if lane_reasons:
            detail = " · ".join(dict.fromkeys(lane_reasons))
        elif artifact is None:
            detail = "Terminal evaluation artifact unavailable"

    return {
        "key": lane,
        "asset_class": _label(lane),
        "status": status,
        "detail": detail,
    }


def _terminal_evaluation_attempt(
    values: Mapping[str, str],
    *,
    release_sha: str | None = None,
    decision_epoch: object = None,
) -> dict[str, object] | None:
    root = _data_root(values) / "all-market-certification"
    pointer = _read_mapping(root / "latest.json")
    if pointer is None:
        return None
    pointer_release = str(pointer.get("release_sha") or "").strip()
    pointer_epoch = pointer.get("decision_epoch")
    if release_sha is not None and pointer_release != release_sha:
        return None
    if decision_epoch is not None and pointer_epoch != decision_epoch:
        return None
    certification_id = str(pointer.get("certification_id") or "").strip()
    if not certification_id or "/" in certification_id or "\\" in certification_id:
        return None

    directory = root / "certifications" / certification_id
    aggregate = _read_mapping(directory / "aggregate.json")
    if aggregate is None:
        return None
    aggregate_body = {
        str(key): value for key, value in aggregate.items() if key != "sha256"
    }
    if (
        aggregate.get("sha256") != _digest(aggregate_body)
        or pointer.get("aggregate_sha256") != aggregate.get("sha256")
    ):
        return None
    certified_flag = aggregate.get("all_market_runtime_certified")
    if (
        aggregate.get("schema_version") != _CERT_SCHEMA
        or aggregate.get("certification_id") != certification_id
        or aggregate.get("release_sha") != pointer_release
        or aggregate.get("decision_epoch") != pointer_epoch
        or not isinstance(certified_flag, bool)
        or aggregate.get("paper_only") is not True
        or aggregate.get("real_money_authorized") is not False
    ):
        return None
    required = aggregate.get("required_lanes")
    raw_blocking = aggregate.get("blocking_reasons", ())
    if not isinstance(required, list) or not required:
        return None
    blocking_reasons = (
        tuple(str(item) for item in raw_blocking)
        if isinstance(raw_blocking, list)
        else ()
    )

    rows: list[dict[str, object]] = []
    for raw_lane in required:
        lane = str(raw_lane).strip().lower()
        if not lane:
            continue
        rows.append(
            _artifact_row(
                directory,
                lane=lane,
                certification_id=certification_id,
                release_sha=pointer_release,
                decision_epoch=pointer_epoch,
                blocking_reasons=blocking_reasons,
            )
        )
    if not rows:
        return None
    all_evaluated = all(row.get("status") == "Evaluated" for row in rows)
    return _summary(
        rows,
        as_of=pointer_epoch,
        source=(
            "Current all-market certification"
            if certified_flag and all_evaluated
            else "Current all-market evaluation"
        ),
    )


def _latest_completed_snapshot(values: Mapping[str, str]) -> dict[str, object] | None:
    root = (
        _data_root(values)
        / "continuous_evidence_plane"
        / "global-discovery"
    )
    pointer = _read_mapping(root / "latest.json")
    if pointer is None:
        return None
    integrity = pointer.get("integrity_sha256")
    pointer_body = {
        str(key): value for key, value in pointer.items() if key != "integrity_sha256"
    }
    if integrity != _digest(pointer_body):
        return None
    if (
        pointer.get("schema_version") != _SNAPSHOT_POINTER_SCHEMA
        or pointer.get("paper_only") is not True
        or pointer.get("real_money_authorized") is not False
    ):
        return None
    snapshot_id = str(pointer.get("snapshot_id") or "").strip()
    if not snapshot_id or "/" in snapshot_id or "\\" in snapshot_id:
        return None
    snapshot = _read_mapping(root / "snapshots" / f"{snapshot_id}.json")
    if snapshot is None:
        return None
    snapshot_body = {
        str(key): value for key, value in snapshot.items() if key != "snapshot_id"
    }
    if (
        snapshot.get("snapshot_id") != snapshot_id
        or _digest(snapshot_body) != snapshot_id
        or snapshot.get("schema_version") != _SNAPSHOT_SCHEMA
        or snapshot.get("paper_only") is not True
        or snapshot.get("real_money_authorized") is not False
    ):
        return None
    raw_lanes = snapshot.get("lanes")
    if not isinstance(raw_lanes, list):
        return None

    rows: list[dict[str, object]] = []
    for raw_lane in raw_lanes:
        if not isinstance(raw_lane, Mapping) or raw_lane.get("scheduled") is not True:
            continue
        lane = str(raw_lane.get("asset_class") or "").strip().lower()
        if not lane:
            continue
        catalog = raw_lane.get("catalog_count")
        deep = raw_lane.get("deep_analyzed_count")
        selected = raw_lane.get("selected")
        selected_count = len(selected) if isinstance(selected, list) else None
        if (
            isinstance(catalog, int)
            and catalog >= 0
            and isinstance(deep, int)
            and deep >= 0
            and selected_count is not None
        ):
            detail = (
                f"{catalog} cataloged · {deep} deep analyzed · "
                f"{selected_count} selected"
            )
        else:
            detail = "Latest comprehensive evaluation complete"
        rows.append(
            {
                "key": lane,
                "asset_class": _label(lane),
                "status": "Evaluated",
                "detail": detail,
            }
        )
    if not rows:
        return None
    return _summary(
        rows,
        as_of=snapshot.get("as_of"),
        source="Latest completed global evaluation",
    )


def load_asset_class_evaluation_status(
    *,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return a credential-safe current evaluation summary for presentation only."""

    resolved = dict(os.environ if values is None else values)
    attempt = _latest_dag_attempt(resolved)
    if attempt is not None:
        terminal = _terminal_evaluation_attempt(
            resolved,
            release_sha=str(attempt["release_sha"]),
            decision_epoch=attempt.get("decision_epoch"),
        )
        if terminal is not None:
            return terminal
        return _summary(
            list(attempt["rows"]),
            as_of=attempt.get("decision_epoch"),
            source="Current comprehensive evaluation attempt",
        )

    release_sha = _release(resolved)
    if release_sha and release_sha != "unknown":
        terminal = _terminal_evaluation_attempt(resolved, release_sha=release_sha)
        if terminal is not None:
            return terminal

    completed = _latest_completed_snapshot(resolved)
    if completed is not None:
        return completed

    return _summary(
        [],
        as_of=None,
        source="No comprehensive asset-class evaluation recorded yet",
    )


__all__ = ["load_asset_class_evaluation_status"]
