from __future__ import annotations

from scripts import enrich_certification_failure_telemetry as telemetry


_RELEASE = "a" * 40


def _snapshot():
    return {
        "diagnostic": {"diagnostic_id": "diag-1", "prequalification_progress": {"active_phase": "crypto"}},
        "paper_only": True,
        "real_money_authorized": False,
    }


def _public(*, state: str = "failed"):
    dag = {
        "state": state,
        "focus_node": "deep-market-evidence:crypto",
        "blocking_node": "deep-market-evidence:crypto",
        "failure_type": "ComprehensiveDiscoverySpoolError",
        "failure_message": "crypto spool payload failed validation",
        "failure_cause_type": "ComprehensiveDiscoverySpoolError",
        "failure_cause_message": "schema mismatch in frozen crypto spool",
        "retryable": False,
        "retry_after": None,
        "node_states": {
            "deep-market-evidence:crypto": {
                "state": state,
                "asset_class": "crypto",
                "failure_type": "ComprehensiveDiscoverySpoolError",
                "failure_message": "crypto spool payload failed validation",
                "failure_cause_type": "ComprehensiveDiscoverySpoolError",
                "failure_cause_message": "schema mismatch in frozen crypto spool",
                "retryable": False,
                "retry_after": None,
            }
        },
        "paper_only": True,
        "real_money_authorized": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
    }
    return {
        "active_release": _RELEASE,
        "diagnostic_id": "diag-1",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "prequalification_progress": {"dag_progress": dag},
    }


def test_failed_dag_cause_survives_safe_telemetry_projection() -> None:
    enriched = telemetry.enrich_snapshot(_snapshot(), _public(), expected_release=_RELEASE)

    dag = enriched["diagnostic"]["prequalification_progress"]["dag_progress"]
    assert dag["blocking_node"] == "deep-market-evidence:crypto"
    assert dag["failure_type"] == "ComprehensiveDiscoverySpoolError"
    assert dag["failure_message"] == "crypto spool payload failed validation"
    assert dag["failure_cause_type"] == "ComprehensiveDiscoverySpoolError"
    assert dag["failure_cause_message"] == "schema mismatch in frozen crypto spool"
    assert dag["paper_only"] is True
    assert dag["real_money_authorized"] is False
    assert dag["decision_authority"] is False
    assert enriched["certification_failure_telemetry_enriched"] is True


def test_nonfailed_dag_does_not_project_failure_text() -> None:
    enriched = telemetry.enrich_snapshot(_snapshot(), _public(state="running"), expected_release=_RELEASE)

    dag = enriched["diagnostic"]["prequalification_progress"]["dag_progress"]
    assert "failure_message" not in dag
    assert "failure_cause_message" not in dag
    node = dag["node_states"]["deep-market-evidence:crypto"]
    assert "failure_message" not in node
    assert "failure_cause_message" not in node


def test_authority_or_credential_unsafe_payload_is_rejected() -> None:
    payload = _public()
    payload["real_money_authorized"] = True

    try:
        telemetry.enrich_snapshot(_snapshot(), payload, expected_release=_RELEASE)
    except ValueError as error:
        assert "real-money authority" in str(error)
    else:
        raise AssertionError("unsafe production diagnostic must be rejected")


def test_dag_without_paper_only_boundary_is_not_projected() -> None:
    payload = _public()
    payload["prequalification_progress"]["dag_progress"]["paper_only"] = False

    enriched = telemetry.enrich_snapshot(_snapshot(), payload, expected_release=_RELEASE)

    assert "dag_progress" not in enriched["diagnostic"]["prequalification_progress"]
    assert "certification_failure_telemetry_enriched" not in enriched
