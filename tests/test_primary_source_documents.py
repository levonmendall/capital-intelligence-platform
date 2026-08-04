from datetime import datetime, timedelta, timezone

import pytest

from intelligence.primary_source_documents import (
    ConclusionType,
    DocumentKind,
    PrimarySourceDocument,
    PrimarySourceDocumentEngine,
)


def _doc(identifier, when, passage):
    return PrimarySourceDocument(
        identifier=identifier,
        kind=DocumentKind.SEC_FILING,
        issuer_identifier="issuer-1",
        published_at=when,
        available_at=when + timedelta(minutes=2),
        sections=(("Guidance", passage),),
        source_uri=f"sec://{identifier}",
    )


def test_time_ordered_change_analysis_preserves_passages():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    result = PrimarySourceDocumentEngine().analyze(
        _doc("current", now, "We expect revenue growth of 8% and higher capex."),
        prior=_doc("prior", now - timedelta(days=90), "We expect revenue growth of 5%."),
        exposures=("issuer-1-equity",),
    )
    conclusion = result.conclusions[0]
    assert conclusion.prior_passage == "We expect revenue growth of 5%."
    assert conclusion.current_passage.startswith("We expect revenue")
    assert conclusion.conclusion_type is ConclusionType.FACT
    assert conclusion.to_dict()["authorizes_portfolio_change"] is False


def test_later_document_cannot_be_used_as_prior():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="time ordered"):
        PrimarySourceDocumentEngine().analyze(
            _doc("current", now, "Current"),
            prior=_doc("future", now + timedelta(days=1), "Future"),
        )
