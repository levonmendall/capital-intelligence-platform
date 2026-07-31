"""Deterministic ordering for persisted JSON artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def parse_embedded_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("embedded artifact timestamp is missing")
    timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("embedded artifact timestamp must include a timezone")
    return timestamp.astimezone(timezone.utc)


def stable_payload_identifier(
    payload: Mapping[str, Any],
    *,
    preferred_fields: Sequence[str] = (),
) -> str:
    for field in preferred_fields:
        value = str(payload.get(field) or "").strip()
        if value:
            return value
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def embedded_artifact_key(
    payload: Mapping[str, Any],
    *,
    timestamp_fields: Sequence[str],
    identifier_fields: Sequence[str] = (),
) -> tuple[datetime, str]:
    for field in timestamp_fields:
        if payload.get(field) not in (None, ""):
            return (
                parse_embedded_utc(payload[field]),
                stable_payload_identifier(
                    payload,
                    preferred_fields=identifier_fields,
                ),
            )
    raise ValueError("artifact has no supported embedded timestamp")


def ordered_json_artifacts(
    paths: Iterable[Path],
    *,
    timestamp_fields: Sequence[str],
    identifier_fields: Sequence[str] = (),
    reverse: bool = True,
) -> tuple[tuple[Path, dict[str, Any]], ...]:
    ranked: list[tuple[tuple[datetime, str], Path, dict[str, Any]]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            key = embedded_artifact_key(
                payload,
                timestamp_fields=timestamp_fields,
                identifier_fields=identifier_fields,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        ranked.append((key, path, payload))
    ranked.sort(key=lambda item: item[0], reverse=reverse)
    return tuple((path, payload) for _, path, payload in ranked)


__all__ = [
    "embedded_artifact_key",
    "ordered_json_artifacts",
    "parse_embedded_utc",
    "stable_payload_identifier",
]
