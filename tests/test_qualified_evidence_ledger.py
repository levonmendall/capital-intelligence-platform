from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from operations import qualified_evidence_ledger as ledger


def _values(tmp_path: Path, release: str = "release-a") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def test_component_reuses_across_release_when_compatibility_is_unchanged(tmp_path: Path) -> None:
    values = _values(tmp_path, "release-a")
    completed = datetime.now(timezone.utc)
    component = ledger.publish_qualified_component(
        values=values,
        component_name="required-public-live",
        compatibility="public-contract-v1",
        completed_at=completed,
        payload={"state": "available", "required_sources_ready": True},
    )

    values["CAPITAL_INTELLIGENCE_RELEASE"] = "release-b"
    loaded = ledger.load_qualified_component(
        values=values,
        component_name="required-public-live",
        compatibility="public-contract-v1",
        cutoff=completed + timedelta(seconds=30),
    )

    assert loaded is not None
    assert loaded.component_id == component.component_id
    assert loaded.observed_release == "release-a"
    assert loaded.payload["required_sources_ready"] is True


def test_component_compatibility_change_forces_refresh(tmp_path: Path) -> None:
    values = _values(tmp_path)
    completed = datetime.now(timezone.utc)
    ledger.publish_qualified_component(
        values=values,
        component_name="required-public-live",
        compatibility="public-contract-v1",
        completed_at=completed,
    )

    assert (
        ledger.load_qualified_component(
            values=values,
            component_name="required-public-live",
            compatibility="public-contract-v2",
            cutoff=completed + timedelta(seconds=1),
        )
        is None
    )


def test_component_specific_freshness_is_enforced(tmp_path: Path) -> None:
    values = _values(tmp_path)
    values[
        "CAPITAL_INTELLIGENCE_EVIDENCE_COMPONENT_REQUIRED_PUBLIC_LIVE_MAX_AGE_SECONDS"
    ] = "60"
    completed = datetime.now(timezone.utc)
    ledger.publish_qualified_component(
        values=values,
        component_name="required-public-live",
        compatibility="public-contract-v1",
        completed_at=completed,
    )

    assert (
        ledger.load_qualified_component(
            values=values,
            component_name="required-public-live",
            compatibility="public-contract-v1",
            cutoff=completed + timedelta(seconds=59),
        )
        is not None
    )
    assert (
        ledger.load_qualified_component(
            values=values,
            component_name="required-public-live",
            compatibility="public-contract-v1",
            cutoff=completed + timedelta(seconds=61),
        )
        is None
    )


def test_component_integrity_tampering_fails_closed(tmp_path: Path) -> None:
    values = _values(tmp_path)
    completed = datetime.now(timezone.utc)
    component = ledger.publish_qualified_component(
        values=values,
        component_name="required-public-live",
        compatibility="public-contract-v1",
        completed_at=completed,
        payload={"state": "available"},
    )
    latest = component.path.with_name("latest.json")
    raw = json.loads(latest.read_text(encoding="utf-8"))
    raw["payload"]["state"] = "failed"
    latest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(
        ledger.QualifiedEvidenceLedgerError,
        match="integrity mismatch",
    ):
        ledger.load_qualified_component(
            values=values,
            component_name="required-public-live",
            compatibility="public-contract-v1",
            cutoff=completed + timedelta(seconds=1),
        )
