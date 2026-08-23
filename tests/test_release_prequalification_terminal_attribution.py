from __future__ import annotations

from pathlib import Path

from operations import release_evidence_prequalification as subject


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-current",
    }


def _completed_dag() -> dict[str, object]:
    return {
        "counts": {
            "required_nodes": 6,
            "completed_nodes": 6,
            "reused_nodes": 0,
            "failed_nodes": 0,
            "running_nodes": 0,
            "pending_nodes": 0,
        },
        "blocking_node": None,
        "focus_node": None,
        "asset_class": None,
        "provider_groups": [],
        "failure_type": None,
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _failed_dag() -> dict[str, object]:
    return {
        "counts": {
            "required_nodes": 6,
            "completed_nodes": 5,
            "reused_nodes": 0,
            "failed_nodes": 1,
            "running_nodes": 0,
            "pending_nodes": 0,
        },
        "blocking_node": "catalog:future",
        "focus_node": "catalog:future",
        "asset_class": "future",
        "provider_groups": ["cme"],
        "failure_type": "ProviderTimeout",
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_completed_dag_cannot_overwrite_later_capability_gate_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "load_release_certification_dag_progress",
        lambda *_args, **_kwargs: _completed_dag(),
    )

    payload = subject.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail=(
            "capability-operating evidence prequalification failed closed; "
            "reason=capability_operating_evidence_unavailable"
        ),
        generation_id="generation-current",
        metrics={
            "attempt": 3,
            "maximum_attempts": 3,
            "capability_operating_evidence_required": 1,
            "capability_operating_evidence_timeout": 0,
            "complete_all_market_coverage_required": 1,
        },
    )

    context = payload["failure_context"]
    assert isinstance(context, dict)
    assert context["capability"] == "capability_operating_evidence"
    assert context["failure_stage"] == "capability_operating_gate"
    assert context["required_information"] == "fresh_capability_operating_snapshot"
    assert context["completeness"] == "incomplete"
    assert "certification_dag_failure" not in str(payload["detail"])
    assert payload["dag_progress"] == _completed_dag()


def test_capability_timeout_is_attributed_to_capability_gate_not_completed_dag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "load_release_certification_dag_progress",
        lambda *_args, **_kwargs: _completed_dag(),
    )

    payload = subject.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail=(
            "capability-operating evidence prequalification failed closed; "
            "reason=capability_operating_evidence_timeout"
        ),
        generation_id="generation-current",
        metrics={
            "capability_operating_evidence_required": 1,
            "capability_operating_evidence_timeout": 1,
        },
    )

    context = payload["failure_context"]
    assert isinstance(context, dict)
    assert context["capability"] == "capability_operating_evidence"
    assert context["failure_stage"] == "capability_operating_gate"
    assert context["reason"] == "deadline_exceeded"
    assert context["error_type"] == "CapabilityOperatingEvidenceTimeout"


def test_genuine_dag_failure_retains_comprehensive_discovery_attribution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "load_release_certification_dag_progress",
        lambda *_args, **_kwargs: _failed_dag(),
    )

    payload = subject.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail="all-market evidence qualification failed",
        generation_id="generation-current",
        metrics={},
    )

    context = payload["failure_context"]
    assert isinstance(context, dict)
    assert context["capability"] == "comprehensive_discovery"
    assert context["failure_stage"] == "certification_dag:future"
    assert context["blocking_node"] == "catalog:future"
    assert context["reason"] == "deadline_exceeded"
    assert context["error_type"] == "ProviderTimeout"
    assert "certification_dag_failure" in str(payload["detail"])


def test_handoff_failure_is_not_rebound_to_capability_gate_from_metrics_alone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "load_release_certification_dag_progress",
        lambda *_args, **_kwargs: _completed_dag(),
    )

    payload = subject.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail="production_context_activation_not_started",
        generation_id="generation-current",
        metrics={
            "capability_operating_evidence_required": 1,
            "current_release_handoff_missing": 1,
        },
    )

    context = payload["failure_context"]
    assert isinstance(context, dict)
    assert context["capability"] != "capability_operating_evidence"
    assert "certification_dag_failure" not in str(payload["detail"])
