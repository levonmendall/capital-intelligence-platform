from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from operations.provider_reconciliation import (
    ProviderBackfillReconciler,
    ProviderReconciliationState,
)
from run_provider_reconciliation import main as reconciliation_main

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)


def _canonical_payload_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_backfill(root: Path) -> Path:
    relative = Path("market-history") / "AAPL.US" / "2026-01-01__2026-01-31.json"
    destination = root / relative
    destination.parent.mkdir(parents=True)
    payload = [{"date": "2026-01-02", "close": 100.0}]
    snapshot = {
        "schema_version": "provider-dataset-snapshot.v1",
        "dataset_type": "market_history",
        "provider_symbol": "AAPL.US",
        "query_as_of": "2026-02-01T00:00:00+00:00",
        "query_start_at": "2026-01-01T00:00:00+00:00",
        "query_end_at": "2026-01-31T23:59:59+00:00",
        "provider": "EODHD",
        "source_version": "eodhd.v1",
        "observed_at": "2026-01-31T23:59:59+00:00",
        "available_at": "2026-01-31T23:59:59+00:00",
        "retrieved_at": "2026-02-01T00:00:01+00:00",
        "quality_state": "live",
        "availability_basis": "provider_timestamp",
        "provider_record_id": "AAPL.US:2026-01",
        "limitations": [],
        "content_hash": _canonical_payload_hash(payload),
        "payload": payload,
        "backfill_task_identifier": "market-history",
    }
    encoded = (json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    destination.write_bytes(encoded)
    artifact_hash = hashlib.sha256(encoded).hexdigest()
    report = {
        "schema_version": "provider-backfill-report.v1",
        "identifier": "provider-backfill:test:2026-02-01",
        "plan_identifier": "provider-backfill-plan:test",
        "evaluated_at": "2026-02-01T00:01:00+00:00",
        "state": "completed",
        "artifact_count": 1,
        "artifacts": [
            {
                "task_identifier": "market-history",
                "provider": "EODHD",
                "provider_symbol": "AAPL.US",
                "dataset_type": "market_history",
                "start_at": "2026-01-01T00:00:00+00:00",
                "end_at": "2026-01-31T23:59:59+00:00",
                "relative_path": relative.as_posix(),
                "content_hash": artifact_hash,
                "reused": False,
            }
        ],
        "failures": [],
        "required_failures": [],
        "real_money_authorized": False,
    }
    (root / "backfill-report.json").write_text(
        json.dumps(report, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def test_completed_immutable_backfill_reconciles(tmp_path: Path) -> None:
    _write_backfill(tmp_path)

    report = ProviderBackfillReconciler().reconcile(tmp_path, evaluated_at=NOW)

    assert report.state is ProviderReconciliationState.PASSED
    assert report.artifact_count == 1
    assert report.reconciled_artifact_count == 1
    assert report.payload_item_count == 1
    assert report.blockers == ()
    assert report.to_dict()["provider_certified"] is False


def test_changed_artifact_is_blocked(tmp_path: Path) -> None:
    artifact = _write_backfill(tmp_path)
    artifact.write_text("{}\n", encoding="utf-8")

    report = ProviderBackfillReconciler().reconcile(tmp_path, evaluated_at=NOW)

    assert report.state is ProviderReconciliationState.BLOCKED
    assert "artifact file hash mismatch" in " ".join(report.blockers)


def test_reconciliation_cli_writes_report(tmp_path: Path, capsys) -> None:
    _write_backfill(tmp_path)
    output = tmp_path / "reconciliation.json"

    exit_code = reconciliation_main(
        (
            "--backfill-directory",
            str(tmp_path),
            "--evaluated-at",
            NOW.isoformat(),
            "--output",
            str(output),
            "--require-passed",
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["state"] == "passed"
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True
