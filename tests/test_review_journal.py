from datetime import datetime, timedelta, timezone

import pytest

from institutional_market.review_journal import DecisionReview, SQLiteDecisionReviewJournal


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _review(identifier: str, **overrides):
    values = {
        "decision_identifier": identifier,
        "reviewed_at": START,
        "score_changed": True,
        "committee_stable": True,
        "veto_active": False,
        "alert_warranted": True,
        "explanation_clear": True,
        "process_classification": "disciplined",
        "notes": "",
    }
    values.update(overrides)
    return DecisionReview(**values)


def test_journal_is_append_only_and_idempotent(tmp_path):
    journal = SQLiteDecisionReviewJournal(tmp_path / "reviews.db")
    review = _review("decision:1")
    journal.append(review)
    journal.append(review)
    assert journal.history() == (review,)
    with pytest.raises(ValueError, match="different content"):
        journal.append(_review("decision:1", notes="changed"))


def test_metrics_aggregate_process_and_explanation_quality(tmp_path):
    journal = SQLiteDecisionReviewJournal(tmp_path / "reviews.db")
    journal.append(_review("decision:1"))
    journal.append(
        _review(
            "decision:2",
            reviewed_at=START + timedelta(days=1),
            committee_stable=False,
            alert_warranted=False,
            explanation_clear=False,
            process_classification="flawed",
        )
    )
    metrics = journal.metrics()
    assert metrics["review_count"] == 2
    assert metrics["disciplined_rate"] == 0.5
    assert metrics["committee_stability_rate"] == 0.5
    assert metrics["explanation_clarity_rate"] == 0.5


def test_invalid_classification_is_rejected():
    with pytest.raises(ValueError, match="classification"):
        _review("decision:1", process_classification="lucky")
