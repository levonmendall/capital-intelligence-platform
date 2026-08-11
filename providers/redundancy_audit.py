"""Credential-safe per-CIO-cycle provider redundancy evidence.

Every provider capability is tracked through the same ordered state model:
configured -> authenticated -> routed -> certified for the evidence role -> attempted
-> used -> failed-over.  The ledger is observational only and grants no CIO,
construction, execution, or real-money authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _text(value: object, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True, order=True)
class ProviderCapabilityKey:
    provider: str
    capability: str
    dataset: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, field_name="provider").lower())
        object.__setattr__(self, "capability", _text(self.capability, field_name="capability").lower())
        object.__setattr__(self, "dataset", _text(self.dataset, field_name="dataset"))

    @property
    def identifier(self) -> str:
        return f"{self.provider}:{self.capability}:{self.dataset}"


@dataclass(frozen=True, slots=True)
class ProviderCapabilityAudit:
    key: ProviderCapabilityKey
    configured: bool = False
    authenticated: bool = False
    routed: bool = False
    certified_for_evidence_role: bool = False
    attempted: bool = False
    used: bool = False
    failed_over: bool = False
    failure_class: str | None = None
    source_identifiers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.key.provider,
            "capability": self.key.capability,
            "dataset": self.key.dataset,
            "configured": self.configured,
            "authenticated": self.authenticated,
            "routed": self.routed,
            "certified_for_evidence_role": self.certified_for_evidence_role,
            "attempted": self.attempted,
            "used": self.used,
            "failed_over": self.failed_over,
            "failure_class": self.failure_class,
            "source_identifiers": list(self.source_identifiers),
        }


class RedundancyAuditLedger:
    """Thread-safe, cycle-scoped append-safe summary of provider routing decisions."""

    def __init__(self, *, cycle_identifier: str, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        self.cycle_identifier = _text(cycle_identifier, field_name="cycle_identifier")
        self.as_of = as_of.astimezone(timezone.utc)
        self._records: dict[ProviderCapabilityKey, ProviderCapabilityAudit] = {}
        self._lock = RLock()

    def declare(
        self,
        key: ProviderCapabilityKey,
        *,
        configured: bool,
        authenticated: bool,
        routed: bool = True,
        certified_for_evidence_role: bool = True,
    ) -> None:
        with self._lock:
            current = self._records.get(key, ProviderCapabilityAudit(key=key))
            self._records[key] = replace(
                current,
                configured=bool(configured),
                authenticated=bool(authenticated),
                routed=bool(routed),
                certified_for_evidence_role=bool(certified_for_evidence_role),
            )

    def attempted(self, key: ProviderCapabilityKey) -> None:
        with self._lock:
            current = self._records.get(key, ProviderCapabilityAudit(key=key))
            self._records[key] = replace(current, attempted=True)

    def failed(self, key: ProviderCapabilityKey, failure_class: str) -> None:
        with self._lock:
            current = self._records.get(key, ProviderCapabilityAudit(key=key))
            self._records[key] = replace(
                current,
                attempted=True,
                failure_class=_text(failure_class, field_name="failure_class"),
            )

    def used(
        self,
        key: ProviderCapabilityKey,
        *,
        source_identifiers: tuple[str, ...] = (),
        failed_over: bool = False,
    ) -> None:
        clean_sources = tuple(
            dict.fromkeys(str(item).strip() for item in source_identifiers if str(item).strip())
        )
        with self._lock:
            current = self._records.get(key, ProviderCapabilityAudit(key=key))
            self._records[key] = replace(
                current,
                attempted=True,
                used=True,
                failed_over=bool(failed_over),
                source_identifiers=clean_sources,
            )

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            records = tuple(self._records[key] for key in sorted(self._records))
        return {
            "schema_version": "provider-redundancy-audit.v2",
            "cycle_identifier": self.cycle_identifier,
            "as_of": self.as_of.isoformat(),
            "credential_values_included": False,
            "decision_authority_granted": False,
            "execution_authority_granted": False,
            "records": [item.to_dict() for item in records],
        }


_LOCK = RLock()
_CURRENT: RedundancyAuditLedger | None = None


def begin_redundancy_cycle(cycle_identifier: str, as_of: datetime) -> RedundancyAuditLedger:
    global _CURRENT
    ledger = RedundancyAuditLedger(cycle_identifier=cycle_identifier, as_of=as_of)
    with _LOCK:
        _CURRENT = ledger
    return ledger


def current_redundancy_ledger() -> RedundancyAuditLedger | None:
    with _LOCK:
        return _CURRENT


def redundancy_audit_snapshot() -> dict[str, Any] | None:
    ledger = current_redundancy_ledger()
    return None if ledger is None else ledger.to_dict()


__all__ = [
    "ProviderCapabilityAudit",
    "ProviderCapabilityKey",
    "RedundancyAuditLedger",
    "begin_redundancy_cycle",
    "current_redundancy_ledger",
    "redundancy_audit_snapshot",
]
