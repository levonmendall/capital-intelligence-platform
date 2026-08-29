from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations import authoritative_comprehensive_discovery as authoritative
from operations import persistent_certification_scheduler as scheduler


def test_failure_detail_surfaces_terminal_crypto_cause(monkeypatch) -> None:
    epoch = datetime(2026, 8, 29, 4, 20, tzinfo=timezone.utc)
    node = scheduler.CertificationNode(
        node_id="deep-market-evidence:crypto",
        asset_class="crypto",
        provider_groups=("alpaca", "coinbase", "kraken"),
        input_fingerprint="crypto-fingerprint",
        deadline=epoch + timedelta(minutes=15),
        decision_eligible_count=8,
    )
    body = {
        "failed_nodes": [node.node_id],
        "completed_nodes": [],
        "reused_nodes": [],
        "node_results": {
            node.node_id: {
                "status": "failed",
                "failure_type": "CertificationSchedulerError",
                "failure_message": "crypto market evidence qualification failed",
                "failure_cause_type": "RuntimeError",
                "failure_cause_message": "coinbase checkpoint integrity failed",
                "retryable": False,
                "retry_after": None,
            }
        },
    }
    monkeypatch.setattr(
        authoritative,
        "_latest_scheduler_body",
        lambda *_args, **_kwargs: body,
    )

    detail = authoritative._failure_detail(
        {},
        release_sha="release-test",
        epoch=epoch,
        nodes=(node,),
        error=scheduler.CertificationSchedulerError("outer scheduler failure"),
    )

    assert "node=deep-market-evidence:crypto" in detail
    assert "asset_class=crypto" in detail
    assert "decision_eligible_count=8" in detail
    assert "retryable=false" in detail
    assert "failure_message=crypto market evidence qualification failed" in detail
    assert "failure_cause_type=RuntimeError" in detail
    assert "failure_cause_message=coinbase checkpoint integrity failed" in detail


def test_failure_detail_remains_compatible_with_legacy_manifest(monkeypatch) -> None:
    epoch = datetime(2026, 8, 29, 4, 20, tzinfo=timezone.utc)
    node = scheduler.CertificationNode(
        node_id="deep-market-evidence:crypto",
        asset_class="crypto",
        provider_groups=("alpaca", "coinbase", "kraken"),
        input_fingerprint="crypto-fingerprint",
        deadline=epoch + timedelta(minutes=15),
        decision_eligible_count=8,
    )
    body = {
        "failed_nodes": [node.node_id],
        "completed_nodes": [],
        "reused_nodes": [],
        "node_results": {
            node.node_id: {
                "status": "failed",
                "failure_type": "CertificationSchedulerError",
                "retry_after": None,
            }
        },
    }
    monkeypatch.setattr(
        authoritative,
        "_latest_scheduler_body",
        lambda *_args, **_kwargs: body,
    )

    detail = authoritative._failure_detail(
        {},
        release_sha="release-test",
        epoch=epoch,
        nodes=(node,),
        error=scheduler.CertificationSchedulerError("outer scheduler failure"),
    )

    assert "failure_type=CertificationSchedulerError" in detail
    assert "retryable=false" in detail
    assert "retry_after=none" in detail
