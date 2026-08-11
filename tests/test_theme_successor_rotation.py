from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from application.global_rotation_cycle import enrich_global_rotation_contexts
from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal, TrendStage
from intelligence.theme_successor import propagate_theme_successors, theme_successor_score

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Context:
    candidate_identifier: str
    forward_intelligence: ForwardIntelligenceBundle | None


def _theme_signal(candidate: str) -> ForwardSignal:
    return ForwardSignal(
        identifier=f"signal:theme:theme:{candidate}:compute",
        as_of=NOW,
        name="AI infrastructure demand transmission",
        channels=("forecast", "fundamental"),
        expected_return_impact=0.08,
        confidence=0.85,
        evidence=("HBM is a modeled downstream bottleneck",),
        contradictory_evidence=("capacity can catch up",),
        assumptions=("AI demand persists",),
        risks=("substitution",),
        change_conditions=("reassess when capacity or demand changes",),
        evidence_identifiers=("evidence:ai-chain",),
    )


def _bundle(candidate: str, *, beneficiary: str | None = None):
    signal = _theme_signal(candidate) if beneficiary is not None else None
    return ForwardIntelligenceBundle(
        identifier=f"forward:{candidate}",
        candidate_identifier=candidate,
        as_of=NOW,
        signals=() if signal is None else (signal,),
        scenarios=(),
        diagnostics=(
            ()
            if beneficiary is None
            else (f"Potential next beneficiaries: {beneficiary}",)
        ),
        model_versions=("structural-theme-transmission.v1",),
        trend_stage=TrendStage.EARLY,
    )


def _candidate(identifier: str, symbol: str):
    return SimpleNamespace(
        identifier=identifier,
        instrument=SimpleNamespace(symbol=symbol),
    )


def test_theme_successor_maps_only_to_existing_governed_candidate_and_has_zero_return_impact():
    source = Context("candidate:compute", _bundle("candidate:compute", beneficiary="HBM"))
    target = Context("candidate:memory", _bundle("candidate:memory"))
    candidates = (
        _candidate("candidate:compute", "GPU"),
        _candidate("candidate:memory", "HBM"),
    )
    propagated = propagate_theme_successors(
        contexts=(source, target),
        candidates=candidates,
    )
    target_bundle = propagated[1].forward_intelligence
    assert target_bundle is not None
    markers = tuple(
        item
        for item in target_bundle.signals
        if item.identifier.startswith("signal:theme-successor:")
    )
    assert len(markers) == 1
    assert markers[0].expected_return_impact == 0.0
    assert markers[0].confidence == 0.85
    score, evidence = theme_successor_score(target_bundle)
    assert score == 0.85
    assert evidence == ("evidence:ai-chain",)


def test_unknown_beneficiary_symbol_is_not_invented_as_a_candidate():
    source = Context("candidate:compute", _bundle("candidate:compute", beneficiary="UNKNOWN"))
    candidates = (_candidate("candidate:compute", "GPU"),)
    propagated = propagate_theme_successors(
        contexts=(source,),
        candidates=candidates,
    )
    assert all(
        not item.identifier.startswith("signal:theme-successor:")
        for item in propagated[0].forward_intelligence.signals
    )


def test_global_rotation_enrichment_propagates_successor_before_leadership_synthesis():
    source = Context("candidate:compute", _bundle("candidate:compute", beneficiary="HBM"))
    target = Context("candidate:memory", _bundle("candidate:memory"))
    candidates = (
        _candidate("candidate:compute", "GPU"),
        _candidate("candidate:memory", "HBM"),
    )
    enriched = enrich_global_rotation_contexts((source, target), candidates)
    target_bundle = enriched[1].forward_intelligence
    assert target_bundle is not None
    assert any(
        item.identifier.startswith("signal:theme-successor:")
        for item in target_bundle.signals
    )
    # Successor evidence raises global research attention but never becomes a direct
    # return contribution by itself.
    assert sum(
        item.expected_return_impact
        for item in target_bundle.signals
        if item.identifier.startswith("signal:theme-successor:")
    ) == 0.0
