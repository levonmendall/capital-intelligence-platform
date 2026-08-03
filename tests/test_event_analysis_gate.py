from __future__ import annotations

from intelligence.event_quality import assess_event_clusters


def _record(
    identifier: str,
    *,
    canonical: str = "event:policy",
    provider: str = "Federal Reserve",
    source_type: str = "official",
    quality_state: str = "live",
    reliability: float = 0.95,
    relevance: float = 0.90,
    materiality: float = 0.90,
    supersedes: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "canonical_event_identifier": canonical,
        "topic": "Federal Reserve cuts rates",
        "summary": "The central bank announces a rate cut and policy easing.",
        "entities": ("Federal Reserve",),
        "instruments": (),
        "impact_channels": ("policy", "discount_rate"),
        "reliability": reliability,
        "relevance": relevance,
        "materiality": materiality,
        "supersedes_identifiers": supersedes,
        "provenance": {
            "provider": provider,
            "source_identifier": f"source:{identifier}",
            "independence_group": provider,
            "source_type": source_type,
            "quality_state": quality_state,
        },
    }


def test_single_official_source_enters_analysis_without_market_confirmation() -> None:
    assessment, _ = assess_event_clusters((_record("official"),))[0]

    assert assessment.eligible_for_analysis
    assert assessment.authoritative_source
    assert assessment.source_sufficient
    assert assessment.market_confirmation == 0.0
    assert not assessment.eligible_for_cio_context


def test_authoritative_source_exception_does_not_weaken_market_gate() -> None:
    assessment, _ = assess_event_clusters(
        (_record("official-confirmed"),),
        market_confirmation={"event:policy": 0.50},
    )[0]

    assert assessment.eligible_for_analysis
    assert assessment.authoritative_source
    assert assessment.eligible_for_cio_context


def test_single_non_authoritative_report_is_analyzed_but_not_escalated() -> None:
    assessment, _ = assess_event_clusters(
        (
            _record(
                "journalism",
                provider="Independent newsroom",
                source_type="journalism",
            ),
        ),
        market_confirmation={"event:policy": 0.50},
    )[0]

    assert assessment.eligible_for_analysis
    assert not assessment.authoritative_source
    assert not assessment.source_sufficient
    assert not assessment.eligible_for_cio_context


def test_explicit_material_update_receives_partial_novelty() -> None:
    records = (
        _record(
            "wire-update",
            provider="Newswire",
            source_type="newswire",
            supersedes=("prior:policy",),
        ),
        _record(
            "official-update",
            provider="Federal Reserve",
            source_type="official",
            supersedes=("prior:policy",),
        ),
    )
    assessment, _ = assess_event_clusters(
        records,
        prior_semantic_keys=("event:policy",),
        market_confirmation={"event:policy": 0.50},
    )[0]

    assert assessment.novelty == 0.75
    assert assessment.eligible_for_analysis
    assert assessment.eligible_for_cio_context


def test_known_event_without_material_update_remains_analysis_only() -> None:
    assessment, _ = assess_event_clusters(
        (_record("repeat"),),
        prior_semantic_keys=("event:policy",),
        market_confirmation={"event:policy": 0.50},
    )[0]

    assert assessment.novelty == 0.0
    assert assessment.eligible_for_analysis
    assert not assessment.eligible_for_cio_context


def test_disputed_event_is_blocked_from_analysis_and_escalation() -> None:
    assessment, _ = assess_event_clusters(
        (_record("disputed", quality_state="disputed"),),
        market_confirmation={"event:policy": 0.50},
    )[0]

    assert not assessment.eligible_for_analysis
    assert not assessment.eligible_for_cio_context


def test_low_materiality_noise_remains_below_analysis_gate() -> None:
    assessment, _ = assess_event_clusters(
        (
            _record(
                "noise",
                reliability=0.90,
                relevance=0.10,
                materiality=0.10,
            ),
        )
    )[0]

    assert not assessment.eligible_for_analysis
    assert not assessment.eligible_for_cio_context
