from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from operations import component_qualified_evidence_maintenance as maintenance
from operations import qualified_evidence_ledger as ledger


def _values(tmp_path):
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-a",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def test_component_ledger_preserves_evidence_cutoff_separate_from_completion(tmp_path) -> None:
    values = _values(tmp_path)
    evidence_as_of = datetime.now(timezone.utc) - timedelta(seconds=30)
    completed_at = evidence_as_of + timedelta(seconds=10)

    component = ledger.publish_qualified_component(
        values=values,
        component_name="component-test",
        compatibility="contract-test",
        as_of=evidence_as_of,
        completed_at=completed_at,
    )
    loaded = ledger.load_qualified_component(
        values=values,
        component_name="component-test",
        compatibility="contract-test",
        cutoff=completed_at + timedelta(seconds=1),
    )

    assert loaded is not None
    assert component.as_of == evidence_as_of
    assert component.completed_at == completed_at
    assert component.valid_through == evidence_as_of + timedelta(seconds=900)


def test_public_component_commits_the_requested_evidence_epoch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    values = _values(tmp_path)
    evidence_as_of = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(
        maintenance,
        "_public_component_compatibility",
        lambda: "public-contract-test",
    )
    monkeypatch.setattr(
        maintenance._legacy_maintenance,
        "_default_public_collector",
        lambda timestamp: SimpleNamespace(
            state="available",
            required_sources_ready=True,
            collection_scope="required",
        ),
    )

    maintenance._component_public_collector(values)(evidence_as_of)
    component = ledger.load_qualified_component(
        values=values,
        component_name=maintenance._PUBLIC_COMPONENT,
        compatibility="public-contract-test",
        cutoff=datetime.now(timezone.utc),
    )

    assert component is not None
    assert component.as_of == evidence_as_of
    assert component.completed_at >= evidence_as_of


def test_still_fresh_public_checkpoint_resumes_the_same_evidence_epoch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    values = _values(tmp_path)
    evidence_as_of = datetime.now(timezone.utc) - timedelta(seconds=30)
    requested = evidence_as_of + timedelta(seconds=60)
    monkeypatch.setattr(
        maintenance,
        "_public_component_compatibility",
        lambda: "public-contract-test",
    )
    ledger.publish_qualified_component(
        values=values,
        component_name=maintenance._PUBLIC_COMPONENT,
        compatibility="public-contract-test",
        as_of=evidence_as_of,
        completed_at=evidence_as_of + timedelta(seconds=5),
        payload={"state": "available", "required_sources_ready": True},
    )

    assert maintenance._resumable_evidence_cutoff(values, requested=requested) == evidence_as_of


def test_exact_discovery_and_history_checkpoint_avoids_provider_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    values = _values(tmp_path)
    evidence_as_of = datetime.now(timezone.utc) - timedelta(seconds=2)
    result = object()
    monkeypatch.setattr(
        maintenance,
        "_discovery_component_compatibility",
        lambda: "discovery-contract-test",
    )
    monkeypatch.setattr(
        maintenance,
        "_history_component_compatibility",
        lambda: "history-contract-test",
    )
    ledger.publish_qualified_component(
        values=values,
        component_name=maintenance._DISCOVERY_COMPONENT,
        compatibility="discovery-contract-test",
        as_of=evidence_as_of,
        payload={"snapshot_id": "snapshot-test", "scheduled_lanes": []},
    )
    ledger.publish_qualified_component(
        values=values,
        component_name=maintenance._HISTORY_COMPONENT,
        compatibility="history-contract-test",
        as_of=evidence_as_of,
        payload={
            "historical_scope_count": 7,
            "historical_coverage_digest": "history-digest",
        },
    )
    monkeypatch.setattr(
        maintenance,
        "load_qualified_comprehensive_discovery_snapshot",
        lambda **_kwargs: SimpleNamespace(snapshot_id="snapshot-test", result=result),
    )
    monkeypatch.setattr(
        maintenance._plane,
        "_historical_coverage_summary",
        lambda *_args, **_kwargs: (7, "history-digest"),
    )
    monkeypatch.setattr(
        maintenance._plane,
        "_default_discovery",
        lambda _timestamp: pytest.fail("qualified discovery must be provider-free"),
    )

    assert maintenance._component_discovery_runner(values)(evidence_as_of) is result


def test_discovery_and_history_compatibility_inputs_exist() -> None:
    repository_root = maintenance.Path(maintenance.__file__).resolve().parents[1]
    for relative in (
        *maintenance._DISCOVERY_COMPATIBILITY_FILES,
        *maintenance._HISTORY_COMPATIBILITY_FILES,
    ):
        assert (repository_root / relative).is_file(), relative
