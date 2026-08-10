from datetime import datetime, timezone

from intelligence.thesis_learning import (
    InvestmentThesisRecord,
    SQLiteDecisionLearningStore,
    ThesisHealth,
)


def test_learning_store_is_append_only_and_idempotent(tmp_path) -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    record = InvestmentThesisRecord(
        identifier="thesis:1",
        candidate_identifier="candidate:1",
        as_of=now,
        rationale="Expected return exceeds alternatives after costs.",
        assumptions=("Demand remains resilient",),
        catalysts=("Earnings",),
        risks=("Demand weakens",),
        invalidation_conditions=("Demand contracts materially",),
        expected_horizon_days=365,
        health=ThesisHealth.UNCHANGED,
        evidence_identifiers=("evidence:1",),
    )
    store = SQLiteDecisionLearningStore(tmp_path / "learning.db")
    first = store.append("investment_thesis", record)
    second = store.append("investment_thesis", record)
    assert first == second == 1
    assert store.verify_integrity()
    assert record.investment_authority is False
