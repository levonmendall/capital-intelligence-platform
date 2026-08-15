from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from operations import certification_input_manifest as certification
from operations import continuous_evidence_plane as plane


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_COMPOSITIONAL_CERTIFICATION_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE": "false",
    }


def _generation(tmp_path: Path, *, as_of: datetime):
    return plane.refresh_continuous_evidence_plane(
        as_of=as_of,
        values=_values(tmp_path),
        reference_preparer=lambda _values: SimpleNamespace(manifest_id="manifest:test"),
        public_collector=lambda _timestamp: SimpleNamespace(state="available"),
        discovery=lambda _timestamp: object(),
    )


def _global_snapshot(as_of: datetime):
    return SimpleNamespace(
        snapshot_id="global-snapshot-test",
        evidence_as_of=as_of,
        held_symbols=(),
        tracked_symbols=(),
    )


def _equity_snapshot(as_of: datetime):
    return SimpleNamespace(
        snapshot_id="equity-snapshot-test",
        evidence_as_of=as_of,
        held_symbols=(),
        tracked_symbols=(),
        excluded_symbols=("SPY", "VTI"),
    )


def _paper_snapshot(as_of: datetime):
    return SimpleNamespace(
        snapshot_id="paper-snapshot-test",
        evidence_as_of=as_of,
        universe_signature="paper-universe-test",
    )


def test_freeze_certification_input_binds_release_evidence_snapshot_and_policy(
    tmp_path: Path,
) -> None:
    as_of = datetime.now(timezone.utc) - timedelta(minutes=2)
    generation = _generation(tmp_path, as_of=as_of)
    cutoff = as_of + timedelta(minutes=1)
    values = _values(tmp_path)
    snapshot = plane.ensure_point_in_time_snapshot(
        cutoff=cutoff,
        values=values,
        allow_refresh=False,
    )

    record = certification.freeze_certification_input(
        cutoff=cutoff,
        values=values,
        snapshot=snapshot,
        global_snapshot=_global_snapshot(generation.as_of),
        equity_snapshot=_equity_snapshot(generation.as_of),
        paper_snapshot=_paper_snapshot(generation.as_of),
    )

    assert record.release == "release-test"
    assert record.evidence_generation_id == generation.generation_id
    assert record.snapshot_id == snapshot.snapshot_id
    assert record.global_discovery_snapshot_id == "global-snapshot-test"
    assert record.us_equity_discovery_snapshot_id == "equity-snapshot-test"
    assert record.paper_evidence_snapshot_id == "paper-snapshot-test"
    assert record.cutoff == cutoff
    assert record.reference_manifest_id == "manifest:test"
    assert record.path.exists()
    payload = json.loads(record.path.read_text(encoding="utf-8"))
    assert payload["global_discovery_snapshot_id"] == "global-snapshot-test"
    assert payload["us_equity_discovery_snapshot_id"] == "equity-snapshot-test"
    assert payload["paper_evidence_snapshot_id"] == "paper-snapshot-test"
    assert payload["consumer_provider_refresh_permitted"] is False
    assert payload["evidence_owner"] == "continuous_evidence_plane"
    assert payload["evidence_certification"] == "certified"
    assert payload["snapshot_certification"] == "frozen"
    assert payload["cio_eligible"] is True
    assert payload["investment_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False

    ledger = (
        tmp_path
        / "all-market-certification-v2"
        / "ledger"
        / "release-test"
        / "latest-input.json"
    )
    assert ledger.exists()
    ledger_payload = json.loads(ledger.read_text(encoding="utf-8"))
    integrity = ledger_payload.pop("integrity_sha256")
    assert integrity == certification._digest(ledger_payload)
    assert ledger_payload["record_id"] == record.record_id
    assert ledger_payload["global_discovery_snapshot_id"] == "global-snapshot-test"
    assert ledger_payload["us_equity_discovery_snapshot_id"] == "equity-snapshot-test"
    assert ledger_payload["paper_evidence_snapshot_id"] == "paper-snapshot-test"


def test_freeze_without_snapshot_can_never_refresh_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    values = _values(tmp_path)
    observed: dict[str, object] = {}
    snapshot = SimpleNamespace(
        snapshot_id="snapshot-test",
        cutoff=cutoff,
        plane_generation_id="generation-test",
        reference_manifest_id="manifest:test",
    )
    generation = plane.EvidencePlaneGeneration(
        generation_id="generation-test",
        as_of=cutoff - timedelta(seconds=5),
        completed_at=cutoff - timedelta(seconds=4),
        reference_manifest_id="manifest:test",
        scheduled_lanes=("future", "us_equity"),
        historical_scope_count=12,
        historical_coverage_digest="history-test",
        public_live_state="available",
    )

    def ensure(**kwargs):
        observed.update(kwargs)
        return snapshot

    monkeypatch.setattr(certification._plane, "ensure_point_in_time_snapshot", ensure)
    monkeypatch.setattr(
        certification._plane,
        "load_latest_evidence_plane",
        lambda _values: generation,
    )

    certification.freeze_certification_input(
        cutoff=cutoff,
        values=values,
        global_snapshot=_global_snapshot(generation.as_of),
        equity_snapshot=_equity_snapshot(generation.as_of),
        paper_snapshot=_paper_snapshot(generation.as_of),
    )

    assert observed["allow_refresh"] is False
    assert observed["cutoff"] == cutoff


def test_policy_compatibility_change_changes_record_identity(tmp_path: Path) -> None:
    as_of = datetime.now(timezone.utc) - timedelta(minutes=2)
    generation = _generation(tmp_path, as_of=as_of)
    cutoff = as_of + timedelta(minutes=1)
    first_values = _values(tmp_path)
    snapshot = plane.ensure_point_in_time_snapshot(
        cutoff=cutoff,
        values=first_values,
        allow_refresh=False,
    )
    global_snapshot = _global_snapshot(generation.as_of)
    equity_snapshot = _equity_snapshot(generation.as_of)
    paper_snapshot = _paper_snapshot(generation.as_of)
    first = certification.freeze_certification_input(
        cutoff=cutoff,
        values=first_values,
        snapshot=snapshot,
        global_snapshot=global_snapshot,
        equity_snapshot=equity_snapshot,
        paper_snapshot=paper_snapshot,
    )

    changed_values = dict(first_values)
    changed_values["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] = "false"
    second = certification.freeze_certification_input(
        cutoff=cutoff,
        values=changed_values,
        snapshot=snapshot,
        global_snapshot=global_snapshot,
        equity_snapshot=equity_snapshot,
        paper_snapshot=paper_snapshot,
    )

    assert second.snapshot_id == first.snapshot_id
    assert second.global_discovery_snapshot_id == first.global_discovery_snapshot_id
    assert second.us_equity_discovery_snapshot_id == first.us_equity_discovery_snapshot_id
    assert second.paper_evidence_snapshot_id == first.paper_evidence_snapshot_id
    assert second.evidence_generation_id == first.evidence_generation_id
    assert second.policy_compatibility_hash != first.policy_compatibility_hash
    assert second.record_id != first.record_id


def test_production_discovery_barrier_is_provider_free_and_publishes_input_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from operations import comprehensive_market_discovery as discovery

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    observed: dict[str, object] = {}
    snapshot = SimpleNamespace(
        snapshot_id="snapshot-test",
        cutoff=cutoff,
        plane_generation_id="generation-test",
    )
    record = SimpleNamespace(record_id="input-test")

    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_RELEASE", "release-test")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", "true")

    def ensure(**kwargs):
        observed["ensure"] = kwargs
        return snapshot

    def freeze(**kwargs):
        observed["freeze"] = kwargs
        return record

    result = discovery._point_in_time_snapshot_barrier(
        cutoff,
        snapshot_loader=ensure,
        input_freezer=freeze,
    )

    assert result is snapshot
    assert observed["ensure"]["allow_refresh"] is False
    assert observed["ensure"]["cutoff"] == cutoff
    assert observed["freeze"]["snapshot"] is snapshot
    assert discovery.os.environ[
        "CAPITAL_INTELLIGENCE_CIO_CERTIFICATION_INPUT_ID"
    ] == "input-test"
    assert discovery.os.environ[
        "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_SNAPSHOT_ID"
    ] == "snapshot-test"
