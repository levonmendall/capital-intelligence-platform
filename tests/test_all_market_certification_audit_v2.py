from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from operations.all_market_certification_audit import public_all_market_certification
from operations.certification_state_machine import CertificationState, advance_certification_state


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _write_integrity(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["integrity_sha256"] = _digest(payload)
    path.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _install_input(tmp_path: Path) -> tuple[dict[str, str], str, datetime, Path]:
    cutoff = datetime(2026, 8, 15, 5, 0, tzinfo=timezone.utc)
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "RENDER_GIT_COMMIT": "release-test",
    }
    material: dict[str, object] = {
        "schema_version": "all-market-certification-input.v2",
        "release": "release-test",
        "evidence_generation_id": "generation-test",
        "evidence_as_of": cutoff.isoformat(),
        "snapshot_id": "pit-test",
        "snapshot_cutoff": cutoff.isoformat(),
        "global_discovery_snapshot_id": "global-test",
        "us_equity_discovery_snapshot_id": "equity-test",
        "paper_evidence_snapshot_id": "paper-test",
        "policy_compatibility_hash": "p" * 64,
        "consumer_provider_refresh_permitted": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    certification_id = _digest(material)
    root = tmp_path / "all-market-certification-v2"
    input_path = root / "inputs" / "release-test" / f"{certification_id}.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps({**material, "record_id": certification_id}, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )

    advance_certification_state(
        certification_id=certification_id,
        target=CertificationState.EVIDENCE_READY,
        source_id="generation-test",
        values=values,
    )
    advance_certification_state(
        certification_id=certification_id,
        target=CertificationState.SNAPSHOT_FROZEN,
        source_id="pit-test",
        values=values,
    )
    ledger = {
        "schema_version": "all-market-certification-input.v2",
        "record_id": certification_id,
        "release": "release-test",
        "evidence_generation_id": "generation-test",
        "snapshot_id": "pit-test",
        "global_discovery_snapshot_id": "global-test",
        "us_equity_discovery_snapshot_id": "equity-test",
        "paper_evidence_snapshot_id": "paper-test",
        "snapshot_cutoff": cutoff.isoformat(),
        "policy_compatibility_hash": "p" * 64,
        "record_path": str(input_path),
        "certification_state": CertificationState.SNAPSHOT_FROZEN.value,
        "cio_eligible": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    _write_integrity(root / "ledger" / "release-test" / "latest-input.json", ledger)
    return values, certification_id, cutoff, input_path


def _advance_through_construction(values: dict[str, str], certification_id: str) -> None:
    for state, source in (
        (CertificationState.SCREENING_COMPLETE, "screening-test"),
        (CertificationState.COMMITTEE_COMPLETE, "committee-test"),
        (CertificationState.CIO_COMPLETE, "cio-test"),
        (CertificationState.CONSTRUCTION_COMPLETE, "construction-test"),
    ):
        advance_certification_state(
            certification_id=certification_id,
            target=state,
            source_id=source,
            values=values,
        )


def test_public_v2_audit_exposes_only_integrity_proven_stages(tmp_path: Path) -> None:
    values, certification_id, _cutoff, _input_path = _install_input(tmp_path)

    initial = public_all_market_certification(values)
    assert initial["all_market_certification_v2_available"] is True
    assert initial["all_market_certification_v2_input_integrity_valid"] is True
    assert initial["all_market_certification_v2_state_integrity_valid"] is True
    assert initial["all_market_evidence_certified"] is True
    assert initial["all_market_screening_certified"] is False
    assert initial["all_market_operational_certified"] is False

    _advance_through_construction(values, certification_id)
    construction = public_all_market_certification(values)
    assert construction["all_market_screening_certified"] is True
    assert construction["all_market_committee_certified"] is True
    assert construction["all_market_cio_certified"] is True
    assert construction["all_market_construction_certified"] is True
    assert construction["all_market_operational_certified"] is False

    advance_certification_state(
        certification_id=certification_id,
        target=CertificationState.NO_ACTION,
        source_id="no-action-test",
        values=values,
    )
    advance_certification_state(
        certification_id=certification_id,
        target=CertificationState.CERTIFIED,
        source_id="certified:no-action-test",
        values=values,
    )
    terminal = public_all_market_certification(values)
    assert terminal["all_market_no_action_certified"] is True
    assert terminal["all_market_paper_implementation_certified"] is False
    assert terminal["all_market_operational_certified"] is True


def test_public_v2_audit_fails_stage_truth_when_input_is_tampered(tmp_path: Path) -> None:
    values, certification_id, _cutoff, input_path = _install_input(tmp_path)
    _advance_through_construction(values, certification_id)

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["paper_evidence_snapshot_id"] = "tampered-paper"
    input_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    audit = public_all_market_certification(values)
    assert audit["all_market_certification_v2_available"] is True
    assert audit["all_market_certification_v2_input_integrity_valid"] is False
    assert audit["all_market_screening_certified"] is False
    assert audit["all_market_committee_certified"] is False
    assert audit["all_market_cio_certified"] is False
    assert audit["all_market_construction_certified"] is False
    assert audit["all_market_operational_certified"] is False
