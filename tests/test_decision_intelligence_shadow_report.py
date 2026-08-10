from types import SimpleNamespace
from datetime import datetime, timezone

from cio.models import CandidateAssetClass
from operations.decision_intelligence_shadow_report import (
    build_candidate_information_completeness_report,
)


def test_shadow_report_surfaces_missing_crypto_information_without_authority() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    candidate = SimpleNamespace(
        identifier="candidate:btc",
        instrument=SimpleNamespace(
            symbol="BTC-USD",
            asset_class=CandidateAssetClass.CRYPTO,
            security_master_snapshot_identifier="master:1",
            security_master_record_identifiers=("record:btc",),
            analytical_coverage=1.0,
        ),
        evidence_identifiers=("market:btc",),
        liquidity_score=0.9,
    )
    evidence = SimpleNamespace(
        candidate_identifier="candidate:btc",
        macro=SimpleNamespace(evidence_identifiers=("macro:1",)),
        company=None,
        asset_valuation=object(),
        forward_intelligence=None,
    )
    report = build_candidate_information_completeness_report(
        as_of=now,
        candidates=(candidate,),
        candidate_evidence=(evidence,),
    )
    assert report["candidate_count"] == 1
    assert report["incomplete_candidate_count"] == 1
    row = report["candidates"][0]
    assert "onchain" in row["missing_dimensions"]
    assert "positioning" in row["missing_dimensions"]
    assert report["investment_authority"] is False
    assert report["execution_authority"] is False


def test_shadow_report_marks_absent_governed_evidence_explicitly_missing() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    candidate = SimpleNamespace(
        identifier="candidate:missing",
        instrument=SimpleNamespace(
            symbol="TEST",
            asset_class=CandidateAssetClass.US_EQUITY,
        ),
    )
    report = build_candidate_information_completeness_report(
        as_of=now,
        candidates=(candidate,),
        candidate_evidence=(),
    )
    row = report["candidates"][0]
    assert row["completeness"] == 0.0
    assert row["missing_dimensions"] == ["governed_candidate_evidence"]
    assert row["decision_complete"] is False
