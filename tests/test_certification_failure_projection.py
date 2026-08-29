from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from operations import certification_failure_projection as projection
from operations import release_evidence_prequalification as release


def test_runtime_projection_preserves_bounded_nested_failure_truth() -> None:
    retry_after = datetime(2026, 8, 29, 7, 0, tzinfo=timezone.utc)
    result = SimpleNamespace(
        failure_type="ComprehensiveDiscoverySpoolError",
        failure_message="spool publication failed",
        failure_cause_type="ProviderResourceBusy",
        failure_cause_message="alpaca provider lease remained busy",
        retryable=True,
        retry_after=retry_after,
    )
    body = {
        "node_states": {
            "deep-market-evidence:crypto": {
                "state": "failed",
                "asset_class": "crypto",
                "provider_groups": ["alpaca", "coinbase", "kraken"],
                "decision_eligible_count": 8,
                "reused": False,
                "failure_type": "ComprehensiveDiscoverySpoolError",
            }
        },
        "paper_only": True,
        "real_money_authorized": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
    }

    projected = projection._augment_runtime_body(
        body,
        results={"deep-market-evidence:crypto": result},
    )
    node = projected["node_states"]["deep-market-evidence:crypto"]

    assert node["failure_message"] == "spool publication failed"
    assert node["failure_cause_type"] == "ProviderResourceBusy"
    assert node["failure_cause_message"] == "alpaca provider lease remained busy"
    assert node["retryable"] is True
    assert node["retry_after"] == retry_after.isoformat()
    assert projected["paper_only"] is True
    assert projected["real_money_authorized"] is False
    assert projected["decision_authority"] is False


def test_release_projection_exposes_exact_failed_node_cause_without_authority() -> None:
    projection._install_release_projection()
    raw = {
        "schema_version": "persistent-certification-runtime.v1",
        "release_sha": "a" * 40,
        "decision_epoch": "2026-08-29T06:35:10+00:00",
        "updated_at": "2026-08-29T06:39:58+00:00",
        "required_nodes": ["deep-market-evidence:crypto"],
        "counts": {
            "completed_nodes": 0,
            "reused_nodes": 0,
            "failed_nodes": 1,
            "running_nodes": 0,
            "pending_nodes": 0,
        },
        "node_states": {
            "deep-market-evidence:crypto": {
                "state": "failed",
                "asset_class": "crypto",
                "provider_groups": ["alpaca", "coinbase", "kraken"],
                "decision_eligible_count": 8,
                "reused": False,
                "failure_type": "ComprehensiveDiscoverySpoolError",
                "failure_message": "spool publication failed",
                "failure_cause_type": "ProviderResourceBusy",
                "failure_cause_message": "alpaca provider lease remained busy",
                "retryable": True,
                "retry_after": "2026-08-29T07:00:00+00:00",
            }
        },
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }

    safe = release._safe_dag_runtime_payload(raw)

    assert safe is not None
    assert safe["blocking_node"] == "deep-market-evidence:crypto"
    assert safe["failure_type"] == "ComprehensiveDiscoverySpoolError"
    assert safe["failure_message"] == "spool publication failed"
    assert safe["failure_cause_type"] == "ProviderResourceBusy"
    assert safe["failure_cause_message"] == "alpaca provider lease remained busy"
    assert safe["retryable"] is True
    assert safe["paper_only"] is True
    assert safe["real_money_authorized"] is False
    assert safe["decision_authority"] is False
    assert safe["candidate_authority"] is False
    assert safe["sizing_authority"] is False
    assert safe["execution_authority"] is False


def test_nonfailed_runtime_state_does_not_project_failure_text() -> None:
    safe = projection._safe_projected_failure_fields(
        {
            "state": "running",
            "failure_message": "must-not-project",
            "failure_cause_type": "MustNotProject",
            "failure_cause_message": "must-not-project",
        }
    )

    assert safe == {}
