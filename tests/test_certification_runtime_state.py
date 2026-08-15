from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from operations.certification_runtime_state import (
    CertificationRuntimeStateError,
    advance_linear_state_for_cutoff,
    complete_certification_for_cutoff,
    resolve_certification_for_cutoff,
)
from operations.certification_state_machine import (
    CertificationState,
    advance_certification_state,
)
from operations.certification_terminal_reconciliation import (
    reconcile_terminal_certification,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "RENDER_GIT_COMMIT": "release-test",
    }


def _write_integrity_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["integrity_sha256"] = _digest(payload)
    path.write_text(
        json.dumps(body, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _install_input(
    tmp_path: Path,
    *,
    certification_id: str,
    cutoff: datetime,
    latest: bool = True,
) -> dict[str, str]:
    values = _values(tmp_path)
    advance_certification_state(
        certification_id=certification_id,
        target=CertificationState.EVIDENCE_READY,
        source_id=f"generation:{certification_id}",
        values=values,
    )
    advance_certification_state(
        certification_id=certification_id,
        target=CertificationState.SNAPSHOT_FROZEN,
        source_id=f"snapshot:{certification_id}",
        values=values,
    )
    pointer: dict[str, object] = {
        "schema_version": "all-market-certification-input.v2",
        "record_id": certification_id,
        "release": "release-test",
        "evidence_generation_id": f"generation:{certification_id}",
        "snapshot_id": f"snapshot:{certification_id}",
        "global_discovery_snapshot_id": f"global:{certification_id}",
        "us_equity_discovery_snapshot_id": f"equity:{certification_id}",
        "paper_evidence_snapshot_id": f"paper:{certification_id}",
        "snapshot_cutoff": cutoff.isoformat(),
        "policy_compatibility_hash": f"policy:{certification_id}",
        "record_path": str(tmp_path / f"{certification_id}.json"),
        "certification_state": CertificationState.SNAPSHOT_FROZEN.value,
        "cio_eligible": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    ledger = tmp_path / "all-market-certification-v2" / "ledger" / "release-test"
    _write_integrity_json(
        ledger / "by-cutoff" / f"{_stamp(cutoff)}.json",
        pointer,
    )
    if latest:
        _write_integrity_json(ledger / "latest-input.json", pointer)
    return values


def _advance_to_construction(
    *,
    cutoff: datetime,
    values: dict[str, str],
) -> None:
    for state, source in (
        (CertificationState.SCREENING_COMPLETE, "screening:test"),
        (CertificationState.COMMITTEE_COMPLETE, "committee:test"),
        (CertificationState.CIO_COMPLETE, "cio:test"),
        (CertificationState.CONSTRUCTION_COMPLETE, "construction:test"),
    ):
        advance_linear_state_for_cutoff(
            cutoff=cutoff,
            target=state,
            source_id=source,
            values=values,
        )


def _fingerprinted(report: dict[str, object]) -> dict[str, object]:
    excluded = {"generated_at", "report_fingerprint", "json_path", "markdown_path"}
    material = {key: value for key, value in report.items() if key not in excluded}
    return {**report, "report_fingerprint": _digest(material)}


def test_exact_cutoff_index_cannot_be_rebound_by_newer_latest_input(
    tmp_path: Path,
) -> None:
    first = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)
    second = datetime(2026, 8, 15, 4, 5, tzinfo=timezone.utc)
    values = _install_input(
        tmp_path,
        certification_id="cert-first",
        cutoff=first,
    )
    _install_input(
        tmp_path,
        certification_id="cert-second",
        cutoff=second,
    )

    binding = resolve_certification_for_cutoff(first, values=values)

    assert binding.certification_id == "cert-first"
    assert binding.cutoff == first
    assert binding.current_state is CertificationState.SNAPSHOT_FROZEN


def test_runtime_lineage_rejects_skipped_stage_and_completes_in_order(
    tmp_path: Path,
) -> None:
    cutoff = datetime(2026, 8, 15, 4, 10, tzinfo=timezone.utc)
    values = _install_input(
        tmp_path,
        certification_id="cert-linear",
        cutoff=cutoff,
    )

    with pytest.raises(CertificationRuntimeStateError, match="prerequisite"):
        advance_linear_state_for_cutoff(
            cutoff=cutoff,
            target=CertificationState.COMMITTEE_COMPLETE,
            source_id="committee:test",
            values=values,
        )

    _advance_to_construction(cutoff=cutoff, values=values)
    complete_certification_for_cutoff(
        cutoff=cutoff,
        outcome=CertificationState.NO_ACTION,
        source_id="no-action:test",
        values=values,
    )

    binding = resolve_certification_for_cutoff(cutoff, values=values)
    assert binding.current_state is CertificationState.CERTIFIED


def test_terminal_reconciliation_keeps_scheduled_execution_pending_then_certifies_completed(
    tmp_path: Path,
) -> None:
    cutoff = datetime(2026, 8, 15, 4, 20, tzinfo=timezone.utc)
    values = _install_input(
        tmp_path,
        certification_id="cert-execution",
        cutoff=cutoff,
    )
    _advance_to_construction(cutoff=cutoff, values=values)

    base_report: dict[str, object] = {
        "schema_version": "cio-pending-transactions.v1",
        "generated_at": cutoff.isoformat(),
        "portfolio_code": "COMPOUNDING",
        "report_state": "pending_transactions",
        "cio_briefing_status": "approved",
        "safe_abstention_recorded": False,
        "comparative_cio_decision_complete": False,
        "summary": "One governed paper transaction is pending.",
        "paper_trading_start_at": cutoff.isoformat(),
        "paper_trading_start_label": "test",
        "launch_state": "active",
        "execution_state": "scheduled",
        "decision_identifier": "decision:test",
        "decision_as_of": cutoff.isoformat(),
        "construction_identifier": "construction:test",
        "construction_status": "approved",
        "transaction_count": 1,
        "transactions": [
            {
                "sequence": 1,
                "symbol": "SPY",
                "side": "buy",
                "from_weight": 0.0,
                "to_weight": 0.1,
                "trade_weight": 0.1,
                "estimated_cost_return": 0.0,
                "reason": "test",
                "funding_for": [],
                "status": "pending_execution",
            }
        ],
        "target_cash_weight": 0.9,
        "turnover": 0.1,
        "estimated_cost_return": 0.0,
        "expected_return_improvement": 0.01,
        "blocks": [],
        "paper_only": True,
        "real_money_authorized": False,
    }
    scheduled = _fingerprinted(base_report)
    pending = reconcile_terminal_certification(scheduled, values=values)
    assert pending is not None
    assert pending["reconciled"] is False
    assert resolve_certification_for_cutoff(
        cutoff, values=values
    ).current_state is CertificationState.CONSTRUCTION_COMPLETE

    completed = _fingerprinted(
        {
            **base_report,
            "execution_state": "completed",
            "transactions": [
                {
                    **base_report["transactions"][0],  # type: ignore[index]
                    "status": "executed",
                }
            ],
        }
    )
    terminal = reconcile_terminal_certification(completed, values=values)
    assert terminal is not None
    assert terminal["reconciled"] is True
    assert terminal["outcome"] == CertificationState.PAPER_IMPLEMENTED.value
    assert resolve_certification_for_cutoff(
        cutoff, values=values
    ).current_state is CertificationState.CERTIFIED
