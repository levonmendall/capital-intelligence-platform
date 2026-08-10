from types import SimpleNamespace

from cio.models import CandidateAssetClass
from intelligence.information_completeness import CandidateInformationCompletenessEngine


def test_candidate_completeness_surfaces_missing_crypto_onchain_and_positioning() -> None:
    candidate = SimpleNamespace(
        identifier="candidate:btc",
        instrument=SimpleNamespace(
            asset_class=CandidateAssetClass.CRYPTO,
            security_master_snapshot_identifier="master:1",
            security_master_record_identifiers=("record:btc",),
            analytical_coverage=1.0,
        ),
        evidence_identifiers=("market:btc",),
        liquidity_score=0.9,
    )
    evidence = SimpleNamespace(
        macro=SimpleNamespace(evidence_identifiers=("macro:1",)),
        company=None,
        asset_valuation=object(),
        forward_intelligence=None,
    )
    result = CandidateInformationCompletenessEngine().assess(candidate, evidence)
    missing = {item.value for item in result.coverage.missing}
    assert "onchain" in missing
    assert "positioning" in missing
    assert not result.coverage.decision_complete
    assert result.investment_authority is False
