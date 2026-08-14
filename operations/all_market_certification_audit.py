"""Credential-safe reader for the immutable compositional all-market certificate.

The discovery engine publishes release/epoch-bound lane artifacts and an integrity-bound
aggregate under the governed data directory. This module exposes only the minimum safe
proof needed by release verification; it has no investment, construction, execution, or
real-money authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path


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


def public_all_market_certification(
    values: Mapping[str, str],
) -> dict[str, object]:
    """Return a redacted integrity check for the current release's lane aggregate."""

    release = _release(values)
    unavailable = {
        "all_market_runtime_certified": False,
        "all_market_certification_integrity_valid": False,
        "all_market_certification_release_matches": False,
        "all_market_certification_id": None,
        "all_market_certification_epoch": None,
        "all_market_certification_aggregate_sha256": None,
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
    integrity_valid = bool(
        embedded_sha
        and embedded_sha == aggregate_sha
        and embedded_sha == _digest(body)
        and str(aggregate.get("certification_id") or "") == certification_id
        and str(aggregate.get("release_sha") or "") == release
        and str(aggregate.get("decision_epoch") or "") == decision_epoch
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
    }


__all__ = ["public_all_market_certification"]
