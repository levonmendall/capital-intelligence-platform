"""Truthful terminal reconciliation for all-market certification v2.

Terminal certification is derived from the persisted canonical CIO pending-transaction
report after CIO authority and paper-execution controls have already acted. Reporting is
kept side-effect free: this reconciler only recognizes two terminal proofs:

* a governed no-action decision with no transactions, or
* a completed paper implementation whose recorded transactions are all executed.

Scheduled, pending, held, paused, blocked, malformed, or contradictory reports never
advance certification. This module grants no investment or execution authority.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from cio_pending_transactions import load_pending_transaction_report
from operations.certification_runtime_state import (
    certification_runtime_enabled,
    complete_certification_for_cutoff,
    resolve_certification_for_cutoff,
)
from operations.certification_state_machine import CertificationState


_REPORT_SCHEMA = "cio-pending-transactions.v1"
_FINGERPRINT_EXCLUDED = frozenset(
    {"generated_at", "report_fingerprint", "json_path", "markdown_path"}
)


class CertificationTerminalReconciliationError(RuntimeError):
    """Raised when a report claims terminal completion without trustworthy proof."""


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CertificationTerminalReconciliationError(f"{field_name} is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise CertificationTerminalReconciliationError(
            f"{field_name} is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CertificationTerminalReconciliationError(
            f"{field_name} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _semantic_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in report.items()
        if key not in _FINGERPRINT_EXCLUDED
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validated_report(report: Mapping[str, Any]) -> Mapping[str, Any]:
    if report.get("schema_version") != _REPORT_SCHEMA:
        raise CertificationTerminalReconciliationError(
            "pending transaction report schema mismatch"
        )
    if report.get("paper_only") is not True or report.get("real_money_authorized") is not False:
        raise CertificationTerminalReconciliationError(
            "pending transaction report violated paper-only authority"
        )
    fingerprint = str(report.get("report_fingerprint") or "").strip()
    if not fingerprint or fingerprint != _semantic_fingerprint(report):
        raise CertificationTerminalReconciliationError(
            "pending transaction report fingerprint mismatch"
        )
    return report


def reconcile_terminal_certification(
    report: Mapping[str, Any] | None = None,
    *,
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object] | None:
    """Reconcile a trustworthy terminal report into the persisted state machine.

    Non-terminal reports return a small status payload without advancing anything.
    Production certification remains fail-closed: contradictory terminal claims raise.
    """

    resolved = dict(os.environ if values is None else values)
    if not certification_runtime_enabled(resolved):
        return None

    loaded = report if report is not None else load_pending_transaction_report()
    if loaded is None:
        return {"reconciled": False, "reason": "report_unavailable"}
    trusted = _validated_report(loaded)
    cutoff = _aware(trusted.get("decision_as_of"), field_name="decision_as_of")
    binding = resolve_certification_for_cutoff(cutoff, values=resolved)

    if binding.current_state is CertificationState.CERTIFIED:
        return {
            "reconciled": True,
            "certification_id": binding.certification_id,
            "state": CertificationState.CERTIFIED.value,
            "reason": "already_certified",
        }

    report_state = str(trusted.get("report_state") or "").strip().lower()
    execution_state = str(trusted.get("execution_state") or "").strip().lower()
    decision_id = str(trusted.get("decision_identifier") or "").strip()
    construction_id = str(trusted.get("construction_identifier") or "").strip()
    fingerprint = str(trusted.get("report_fingerprint") or "").strip()
    transactions_raw = trusted.get("transactions")
    transactions = (
        list(transactions_raw)
        if isinstance(transactions_raw, list)
        else []
    )
    transaction_count = trusted.get("transaction_count")
    if isinstance(transaction_count, bool) or not isinstance(transaction_count, int):
        raise CertificationTerminalReconciliationError(
            "pending transaction count is invalid"
        )
    if transaction_count != len(transactions):
        raise CertificationTerminalReconciliationError(
            "pending transaction count does not match report rows"
        )

    metadata = {
        "report_fingerprint": fingerprint,
        "decision_identifier": decision_id,
        "construction_identifier": construction_id,
        "transaction_count": transaction_count,
        "execution_state": execution_state,
    }

    if report_state == "no_transaction_recommended":
        if transaction_count != 0:
            raise CertificationTerminalReconciliationError(
                "no-action report contains transactions"
            )
        if trusted.get("safe_abstention_recorded") is not True:
            raise CertificationTerminalReconciliationError(
                "no-action report lacks governed abstention proof"
            )
        if not decision_id:
            raise CertificationTerminalReconciliationError(
                "no-action report lacks decision identity"
            )
        source = f"canonical-no-action:{decision_id}:{fingerprint}"
        complete_certification_for_cutoff(
            cutoff=cutoff,
            outcome=CertificationState.NO_ACTION,
            source_id=source,
            values=resolved,
            detail="persisted canonical CIO report proves governed no-action",
            metadata=metadata,
        )
        return {
            "reconciled": True,
            "certification_id": binding.certification_id,
            "state": CertificationState.CERTIFIED.value,
            "outcome": CertificationState.NO_ACTION.value,
        }

    if execution_state == "completed":
        if report_state != "pending_transactions":
            raise CertificationTerminalReconciliationError(
                "completed execution report is not a transaction report"
            )
        if transaction_count < 1:
            raise CertificationTerminalReconciliationError(
                "completed execution report contains no transactions"
            )
        if not construction_id or not decision_id:
            raise CertificationTerminalReconciliationError(
                "completed execution report lacks canonical identities"
            )
        if any(
            not isinstance(item, Mapping)
            or str(item.get("status") or "").strip().lower() != "executed"
            for item in transactions
        ):
            raise CertificationTerminalReconciliationError(
                "completed execution report contains a non-executed transaction"
            )
        source = f"paper-implementation:{construction_id}:{fingerprint}"
        complete_certification_for_cutoff(
            cutoff=cutoff,
            outcome=CertificationState.PAPER_IMPLEMENTED,
            source_id=source,
            values=resolved,
            detail="persisted canonical report proves completed paper implementation",
            metadata=metadata,
        )
        return {
            "reconciled": True,
            "certification_id": binding.certification_id,
            "state": CertificationState.CERTIFIED.value,
            "outcome": CertificationState.PAPER_IMPLEMENTED.value,
        }

    # Timing and implementation states are intentionally not analytical failures and
    # intentionally not terminal successes. Existing launch/session/liquidity/execution
    # controls remain authoritative.
    return {
        "reconciled": False,
        "certification_id": binding.certification_id,
        "state": binding.current_state.value,
        "reason": f"implementation_{execution_state or 'not_completed'}",
    }


__all__ = [
    "CertificationTerminalReconciliationError",
    "reconcile_terminal_certification",
]
