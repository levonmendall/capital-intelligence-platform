"""Durable, idempotent all-market certification state transitions.

The state machine is operational lineage only.  It does not grant specialist, CIO,
construction, execution, or real-money authority.  Each owner advances only the state it
can truthfully prove; missing prerequisites fail closed and no stage is inferred from a
later artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping


_SCHEMA = "all-market-certification-state.v2"


class CertificationState(str, Enum):
    EVIDENCE_READY = "EVIDENCE_READY"
    SNAPSHOT_FROZEN = "SNAPSHOT_FROZEN"
    SCREENING_COMPLETE = "SCREENING_COMPLETE"
    COMMITTEE_COMPLETE = "COMMITTEE_COMPLETE"
    CIO_COMPLETE = "CIO_COMPLETE"
    CONSTRUCTION_COMPLETE = "CONSTRUCTION_COMPLETE"
    PAPER_IMPLEMENTED = "PAPER_IMPLEMENTED"
    NO_ACTION = "NO_ACTION"
    CERTIFIED = "CERTIFIED"


_ALLOWED_NEXT: Mapping[CertificationState | None, frozenset[CertificationState]] = {
    None: frozenset({CertificationState.EVIDENCE_READY}),
    CertificationState.EVIDENCE_READY: frozenset({CertificationState.SNAPSHOT_FROZEN}),
    CertificationState.SNAPSHOT_FROZEN: frozenset({CertificationState.SCREENING_COMPLETE}),
    CertificationState.SCREENING_COMPLETE: frozenset({CertificationState.COMMITTEE_COMPLETE}),
    CertificationState.COMMITTEE_COMPLETE: frozenset({CertificationState.CIO_COMPLETE}),
    CertificationState.CIO_COMPLETE: frozenset({CertificationState.CONSTRUCTION_COMPLETE}),
    CertificationState.CONSTRUCTION_COMPLETE: frozenset(
        {CertificationState.PAPER_IMPLEMENTED, CertificationState.NO_ACTION}
    ),
    CertificationState.PAPER_IMPLEMENTED: frozenset({CertificationState.CERTIFIED}),
    CertificationState.NO_ACTION: frozenset({CertificationState.CERTIFIED}),
    CertificationState.CERTIFIED: frozenset(),
}


class CertificationStateError(RuntimeError):
    """Raised when certification lineage is corrupt or a transition is invalid."""


@dataclass(frozen=True, slots=True)
class CertificationStateRecord:
    certification_id: str
    state: CertificationState
    sequence: int
    source_id: str
    event_sha256: str
    path: Path


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _root(values: Mapping[str, str]) -> Path:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        raise CertificationStateError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for certification state"
        )
    return Path(raw).expanduser() / "all-market-certification-v2" / "state"


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise CertificationStateError(
                f"immutable certification state collision at {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise CertificationStateError(
                f"immutable certification state collision at {path.name}"
            )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    body = dict(payload)
    body["integrity_sha256"] = _digest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(body, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_latest(
    values: Mapping[str, str],
    certification_id: str,
) -> Mapping[str, object] | None:
    path = _root(values) / certification_id / "latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise CertificationStateError("certification state pointer is unreadable") from error
    if not isinstance(payload, Mapping):
        raise CertificationStateError("certification state pointer is malformed")
    body = dict(payload)
    integrity = body.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(body):
        raise CertificationStateError("certification state pointer integrity mismatch")
    if body.get("schema_version") != _SCHEMA:
        raise CertificationStateError("certification state schema mismatch")
    if body.get("certification_id") != certification_id:
        raise CertificationStateError("certification state identity mismatch")
    if body.get("paper_only") is not True or body.get("real_money_authorized") is not False:
        raise CertificationStateError("certification state authority boundary is invalid")
    return body


def advance_certification_state(
    *,
    certification_id: str,
    target: CertificationState,
    source_id: str,
    values: Mapping[str, str] | None = None,
    detail: str = "",
    metadata: Mapping[str, object] | None = None,
) -> CertificationStateRecord:
    """Advance one canonical certification state exactly once.

    Repeating the already-current state with the same source is idempotent.  Skipping a
    prerequisite, changing the source for an already-published state, or advancing after
    terminal certification fails closed.
    """

    resolved = dict(os.environ if values is None else values)
    normalized_id = str(certification_id).strip()
    normalized_source = str(source_id).strip()
    if not normalized_id or not normalized_source:
        raise ValueError("certification_id and source_id are required")
    if not isinstance(target, CertificationState):
        target = CertificationState(str(target))

    latest = _load_latest(resolved, normalized_id)
    previous_state: CertificationState | None = None
    previous_sha = ""
    previous_sequence = 0
    if latest is not None:
        previous_state = CertificationState(str(latest["state"]))
        previous_sha = str(latest["event_sha256"])
        previous_sequence = int(latest["sequence"])
        if previous_state == target:
            if str(latest.get("source_id") or "") != normalized_source:
                raise CertificationStateError(
                    "idempotent certification state replay changed its source"
                )
            event_path = (
                _root(resolved)
                / normalized_id
                / "events"
                / str(latest["event_filename"])
            )
            return CertificationStateRecord(
                certification_id=normalized_id,
                state=target,
                sequence=previous_sequence,
                source_id=normalized_source,
                event_sha256=previous_sha,
                path=event_path,
            )

    allowed = _ALLOWED_NEXT.get(previous_state, frozenset())
    if target not in allowed:
        prior = "NONE" if previous_state is None else previous_state.value
        raise CertificationStateError(
            f"invalid certification transition {prior} -> {target.value}"
        )

    sequence = previous_sequence + 1
    event_body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "certification_id": normalized_id,
        "sequence": sequence,
        "previous_state": None if previous_state is None else previous_state.value,
        "state": target.value,
        "source_id": normalized_source,
        "detail": str(detail)[:1000],
        "metadata": dict(metadata or {}),
        "previous_event_sha256": previous_sha,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "investment_authority": False,
        "specialist_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    event_sha = _digest(event_body)
    event = {**event_body, "event_sha256": event_sha}
    event_filename = f"{sequence:02d}-{target.value.lower()}-{event_sha[:20]}.json"
    event_path = _root(resolved) / normalized_id / "events" / event_filename
    _immutable_json(event_path, event)
    _atomic_json(
        _root(resolved) / normalized_id / "latest.json",
        {
            "schema_version": _SCHEMA,
            "certification_id": normalized_id,
            "state": target.value,
            "sequence": sequence,
            "source_id": normalized_source,
            "event_sha256": event_sha,
            "event_filename": event_filename,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )
    return CertificationStateRecord(
        certification_id=normalized_id,
        state=target,
        sequence=sequence,
        source_id=normalized_source,
        event_sha256=event_sha,
        path=event_path,
    )


__all__ = [
    "CertificationState",
    "CertificationStateError",
    "CertificationStateRecord",
    "advance_certification_state",
]
