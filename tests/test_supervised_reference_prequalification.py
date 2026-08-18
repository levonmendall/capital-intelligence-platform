from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import component_qualified_evidence_maintenance as maintenance
from operations import supervised_reference_prequalification as reference
from operations.reference_readiness import ReferenceReadinessError
from operations.supervised_component_execution import SupervisedComponentTimeout
from scripts.enrich_render_production_telemetry import enrich_snapshot


AS_OF = datetime(2026, 8, 17, 23, 30, tzinfo=timezone.utc)


def test_reference_progress_is_credential_safe_and_component_addressable(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    components = {
        "reference-directories": reference._component_row(
            "reference-directories",
            provider="eodhd",
            state="reused",
            required=True,
        ),
        "reference-futures-contracts": reference._component_row(
            "reference-futures-contracts",
            provider="cme-massive",
            state="timed-out",
            required=True,
            failure_type="timeout",
        ),
    }

    reference._write_progress(
        values=values,
        cutoff=AS_OF,
        required_components=("reference-directories", "reference-futures-contracts"),
        components=components,
        active_component=None,
        state="incomplete",
    )

    progress = reference.load_reference_prequalification_progress(values)
    assert progress is not None
    assert progress["state"] == "incomplete"
    assert progress["required_count"] == 2
    assert progress["qualified_count"] == 1
    assert progress["reused_count"] == 1
    assert progress["failed_count"] == 1
    assert progress["failures"] == [
        {
            "component": "reference-futures-contracts",
            "provider": "cme-massive",
            "failure_type": "timeout",
        }
    ]
    assert progress["credential_safe"] is True
    assert progress["paper_only"] is True
    assert progress["real_money_authorized"] is False


def test_reference_component_timeout_is_precisely_attributed(monkeypatch) -> None:
    def timeout(**_kwargs):
        raise SupervisedComponentTimeout("worker exceeded its execution budget")

    monkeypatch.setattr(reference, "run_supervised_component", timeout)

    with pytest.raises(
        maintenance._plane.ContinuousEvidencePlaneError,
        match=r"failure_type=timeout; component=reference-futures-contracts; provider=cme-massive",
    ):
        reference._run_component(
            values={"CAPITAL_INTELLIGENCE_EVIDENCE_REFERENCE_COMPONENT_TIMEOUT_SECONDS": "5"},
            component="reference-futures-contracts",
            provider="cme-massive",
            operation=lambda: None,
            return_value=False,
        )


def test_directory_component_reuse_requires_every_scheduled_release_lane() -> None:
    component = {
        "catalogs": {
            CandidateAssetClass.INTERNATIONAL_EQUITY.value: [{"symbol": "7203.T"}],
            CandidateAssetClass.FX.value: [],
            CandidateAssetClass.FUTURE.value: [{"symbol": "ESZ6"}],
        }
    }
    active_lanes = frozenset(
        {
            CandidateAssetClass.INTERNATIONAL_EQUITY,
            CandidateAssetClass.FX,
            CandidateAssetClass.FUTURE,
        }
    )

    assert reference._missing_required_directory_lanes(
        component,
        active_lanes=active_lanes,
    ) == (CandidateAssetClass.FX.value,)

    component["catalogs"][CandidateAssetClass.FX.value] = [{"symbol": "EURUSD.FOREX"}]
    assert reference._missing_required_directory_lanes(
        component,
        active_lanes=active_lanes,
    ) == ()


def test_strict_release_binding_failure_cannot_be_called_qualified(monkeypatch) -> None:
    def fail(_values, *, now):
        assert now >= AS_OF
        raise ReferenceReadinessError(
            "release-independent reference components are missing or stale: crypto"
        )

    monkeypatch.setattr(
        reference._release_binding,
        "bind_reference_manifest_from_components",
        fail,
    )

    with pytest.raises(
        maintenance._plane.ContinuousEvidencePlaneError,
        match=(
            r"reference prequalification components are not release-bindable; "
            r"failure_type=release_binding_failure; .*crypto"
        ),
    ):
        reference._strict_release_binding(
            {"CAPITAL_INTELLIGENCE_RELEASE": "release-test"},
            minimum_cutoff=AS_OF,
        )


def test_strict_release_binding_returns_exact_release_manifest(monkeypatch) -> None:
    manifest = SimpleNamespace(manifest_id="strict-manifest")
    observed: dict[str, datetime] = {}

    def bind(_values, *, now):
        observed["cutoff"] = now
        return manifest

    monkeypatch.setattr(
        reference._release_binding,
        "bind_reference_manifest_from_components",
        bind,
    )

    result = reference._strict_release_binding(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-test"},
        minimum_cutoff=AS_OF,
    )

    assert result is manifest
    assert observed["cutoff"] >= AS_OF


def test_component_maintenance_does_not_wrap_reference_controller_in_aggregate_supervisor(
    monkeypatch,
) -> None:
    calls = {"bind": 0, "prepare": 0}
    manifest = SimpleNamespace(manifest_id="manifest-ready")

    def bind(_values, *, now):
        calls["bind"] += 1
        assert now.tzinfo is not None
        if calls["bind"] == 1:
            raise ReferenceReadinessError("missing reference component")
        return manifest

    def prepare(_values):
        calls["prepare"] += 1
        return manifest

    monkeypatch.setattr(maintenance, "bind_reference_manifest_from_components", bind)
    monkeypatch.setattr(maintenance, "prepare_supervised_reference_prequalification", prepare)
    monkeypatch.setattr(
        maintenance,
        "_run_supervised",
        lambda *_args, **_kwargs: pytest.fail(
            "aggregate reference supervisor must not wrap component supervisors"
        ),
    )

    result, cutoff = maintenance._bound_or_prepare_reference_manifest(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-test"},
        preparation_cutoff=AS_OF,
    )

    assert result is manifest
    assert cutoff >= AS_OF
    assert calls == {"bind": 2, "prepare": 1}


def test_terminal_telemetry_enrichment_keeps_reference_component_failure() -> None:
    snapshot = {
        "diagnostic": {
            "diagnostic_id": "request-1",
            "progress_metrics": {},
        }
    }
    public_payload = {
        "active_release": "release-test",
        "request_id": "request-1",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "reference_prequalification_progress": {
            "state": "incomplete",
            "updated_at": AS_OF.isoformat(),
            "required_count": 2,
            "qualified_count": 1,
            "reused_count": 1,
            "newly_qualified_count": 0,
            "failed_count": 1,
            "pending_count": 0,
            "active_component": None,
            "components": [
                {
                    "component": "reference-directories",
                    "provider": "eodhd",
                    "state": "reused",
                    "required": True,
                    "failure_type": None,
                },
                {
                    "component": "reference-futures-contracts",
                    "provider": "cme-massive",
                    "state": "timed-out",
                    "required": True,
                    "failure_type": "timeout",
                },
            ],
        },
        "prequalification_progress": {"active_phase": "reference"},
        "prequalification_failure_provider": "cme-massive",
        "prequalification_failure_reason": "deadline_exceeded",
    }

    enriched = enrich_snapshot(
        snapshot,
        public_payload,
        expected_release="release-test",
    )

    diagnostic = enriched["diagnostic"]
    assert diagnostic["reference_prequalification_progress"]["failed_count"] == 1
    assert diagnostic["reference_prequalification_progress"]["failures"] == [
        {
            "component": "reference-futures-contracts",
            "provider": "cme-massive",
            "failure_type": "timeout",
        }
    ]
    assert diagnostic["prequalification_progress"]["active_phase"] == "reference"
    assert diagnostic["prequalification_failure_provider"] == "cme-massive"
    assert diagnostic["prequalification_failure_reason"] == "deadline_exceeded"
