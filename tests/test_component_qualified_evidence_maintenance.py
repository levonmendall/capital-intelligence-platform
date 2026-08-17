from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations import component_qualified_evidence_maintenance as maintenance
from operations.continuous_evidence_plane import EvidencePlaneGeneration
from operations.qualified_evidence_maintenance import EvidenceMaintenanceResult


def _generation(*, as_of: datetime, manifest_id: str = "manifest-old") -> EvidencePlaneGeneration:
    return EvidencePlaneGeneration(
        generation_id="generation-old",
        as_of=as_of,
        completed_at=as_of + timedelta(seconds=1),
        reference_manifest_id=manifest_id,
        scheduled_lanes=("future",),
        historical_scope_count=11,
        historical_coverage_digest="history-digest",
        public_live_state="available",
    )


def test_public_compatibility_inputs_resolve_from_repository() -> None:
    repository_root = Path(maintenance.__file__).resolve().parents[1]
    missing = [
        relative
        for relative in maintenance._PUBLIC_COMPATIBILITY_FILES
        if not (repository_root / relative).is_file()
    ]

    assert missing == []
    fingerprint = maintenance._public_component_compatibility()
    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)


def test_prior_release_generation_rebinds_without_legacy_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    current = _generation(as_of=now - timedelta(minutes=2))
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-new",
    }
    rebound = _generation(as_of=current.as_of, manifest_id="manifest-new")
    rebound = EvidencePlaneGeneration(
        generation_id="generation-new",
        as_of=rebound.as_of,
        completed_at=now,
        reference_manifest_id=rebound.reference_manifest_id,
        scheduled_lanes=rebound.scheduled_lanes,
        historical_scope_count=rebound.historical_scope_count,
        historical_coverage_digest=rebound.historical_coverage_digest,
        public_live_state=rebound.public_live_state,
    )
    calls = {"bind": 0, "legacy": 0}

    monkeypatch.setattr(maintenance._plane, "evidence_plane_enabled", lambda _values: True)
    monkeypatch.setattr(maintenance._plane, "load_latest_evidence_plane", lambda _values: current)
    monkeypatch.setattr(maintenance, "_latest_payload", lambda _values: {"release": "release-old"})
    monkeypatch.setattr(maintenance, "_generation_base_qualified", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        maintenance,
        "_load_public_component",
        lambda _values, *, cutoff: SimpleNamespace(component_id="public-component"),
    )

    def bind(_values, *, now):
        calls["bind"] += 1
        assert now == current.as_of
        return SimpleNamespace(manifest_id="manifest-new")

    monkeypatch.setattr(maintenance, "bind_reference_manifest_from_components", bind)
    monkeypatch.setattr(maintenance, "_publish_release_rebind", lambda **_kwargs: rebound)
    monkeypatch.setattr(
        maintenance._legacy_maintenance,
        "_archive_generation",
        lambda _values, _generation: Path(tmp_path) / "archive.json",
    )

    def unexpected_legacy(**_kwargs):
        calls["legacy"] += 1
        raise AssertionError("provider/reference refresh must not run for a fresh rebind")

    monkeypatch.setattr(
        maintenance._legacy_maintenance,
        "maintain_continuous_evidence_plane",
        unexpected_legacy,
    )

    result = maintenance.maintain_component_qualified_evidence_plane(
        as_of=now,
        values=values,
    )

    assert result.state == "release_rebound"
    assert result.refreshed is False
    assert result.preparation_passes == 0
    assert result.generation.generation_id == "generation-new"
    assert calls == {"bind": 1, "legacy": 0}


def test_prior_release_rebind_requires_compatible_public_component(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    current = _generation(as_of=now - timedelta(minutes=2))
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-new",
    }
    expected = EvidenceMaintenanceResult(
        generation=_generation(as_of=now, manifest_id="manifest-components"),
        state="refreshed",
        refreshed=True,
        preparation_passes=1,
        archived_generation_path=Path(tmp_path) / "archive.json",
    )

    monkeypatch.setattr(maintenance._plane, "evidence_plane_enabled", lambda _values: True)
    monkeypatch.setattr(maintenance._plane, "load_latest_evidence_plane", lambda _values: current)
    monkeypatch.setattr(maintenance, "_latest_payload", lambda _values: {"release": "release-old"})
    monkeypatch.setattr(maintenance, "_generation_base_qualified", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(maintenance, "_load_public_component", lambda _values, *, cutoff: None)
    monkeypatch.setattr(
        maintenance,
        "bind_reference_manifest_from_components",
        lambda _values, *, now: SimpleNamespace(manifest_id="manifest-components"),
    )
    monkeypatch.setattr(maintenance, "_legacy_refresh", lambda **_kwargs: expected)
    monkeypatch.setattr(
        maintenance,
        "_publish_release_rebind",
        lambda **_kwargs: pytest.fail("incompatible public evidence must not be rebound"),
    )

    result = maintenance.maintain_component_qualified_evidence_plane(
        as_of=now,
        values=values,
    )

    assert result is expected


def test_refresh_uses_provider_free_manifest_when_components_are_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-new",
    }
    manifest = SimpleNamespace(manifest_id="manifest-components")
    expected = EvidenceMaintenanceResult(
        generation=_generation(as_of=now, manifest_id=manifest.manifest_id),
        state="refreshed",
        refreshed=True,
        preparation_passes=1,
        archived_generation_path=Path(tmp_path) / "archive.json",
    )

    monkeypatch.setattr(maintenance._plane, "evidence_plane_enabled", lambda _values: True)
    monkeypatch.setattr(maintenance._plane, "load_latest_evidence_plane", lambda _values: None)
    monkeypatch.setattr(maintenance, "_latest_payload", lambda _values: None)
    monkeypatch.setattr(
        maintenance,
        "bind_reference_manifest_from_components",
        lambda _values, *, now: manifest,
    )

    def legacy(**kwargs):
        prepared = kwargs["reference_preparer"](kwargs["values"])
        assert prepared is manifest
        assert callable(kwargs["public_collector"])
        return expected

    monkeypatch.setattr(
        maintenance._legacy_maintenance,
        "maintain_continuous_evidence_plane",
        legacy,
    )

    result = maintenance.maintain_component_qualified_evidence_plane(
        as_of=now,
        values=values,
    )

    assert result is expected


def test_qualified_public_component_survives_release_and_avoids_recollection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-a",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }
    calls = {"public": 0}
    monkeypatch.setattr(
        maintenance,
        "_public_component_compatibility",
        lambda: "public-contract-test",
    )

    def public(timestamp):
        assert timestamp.tzinfo is not None
        calls["public"] += 1
        return SimpleNamespace(
            state="available",
            required_sources_ready=True,
            collection_scope="required",
        )

    monkeypatch.setattr(maintenance._legacy_maintenance, "_default_public_collector", public)
    collector = maintenance._component_public_collector(values)

    first = collector(datetime.now(timezone.utc))
    values["CAPITAL_INTELLIGENCE_RELEASE"] = "release-b"
    second = collector(datetime.now(timezone.utc))

    assert first.required_sources_ready is True
    assert second.required_sources_ready is True
    assert second.qualified_component_reused is True
    assert second.qualified_component_id
    assert calls == {"public": 1}
