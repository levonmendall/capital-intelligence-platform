"""Propagate governed structural-theme bottlenecks to named next beneficiaries.

`StructuralThemeEngine` already computes multi-hop demand transmission, bottlenecks,
lags, and `next_beneficiaries`. Its canonical bundle records those symbols in a stable
diagnostic. This module maps that already-governed output onto candidates that are
already in the same point-in-time opportunity set. The propagated signal has zero
return impact: it raises research/rotation attention but cannot manufacture economics.
"""
from __future__ import annotations

from dataclasses import replace
from statistics import fmean

from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal

_DIAGNOSTIC_PREFIX = "Potential next beneficiaries: "
_SIGNAL_PREFIX = "signal:theme-successor:"
_POLICY_VERSION = "theme-successor-rotation.v1"


def _symbols(bundle: ForwardIntelligenceBundle) -> tuple[str, ...]:
    values: list[str] = []
    for item in bundle.diagnostics:
        if not item.startswith(_DIAGNOSTIC_PREFIX):
            continue
        values.extend(
            token.strip().upper()
            for token in item[len(_DIAGNOSTIC_PREFIX):].split(",")
            if token.strip()
        )
    return tuple(dict.fromkeys(values))


def _theme_signal(bundle: ForwardIntelligenceBundle) -> ForwardSignal | None:
    return next(
        (item for item in bundle.signals if item.identifier.startswith("signal:theme:")),
        None,
    )


def propagate_theme_successors(
    *,
    contexts: tuple[object, ...],
    candidates: tuple[object, ...],
) -> tuple[object, ...]:
    """Attach zero-impact successor evidence to already-governed beneficiary candidates."""

    if not isinstance(contexts, tuple) or not isinstance(candidates, tuple):
        raise TypeError("contexts and candidates must be tuples")
    candidate_by_identifier = {
        str(getattr(item, "identifier")): item for item in candidates
    }
    symbol_to_identifier = {
        str(getattr(getattr(item, "instrument"), "symbol")).upper(): str(
            getattr(item, "identifier")
        )
        for item in candidates
    }
    sources_by_target: dict[str, list[tuple[str, ForwardSignal]]] = {}
    for context in contexts:
        bundle = getattr(context, "forward_intelligence", None)
        if not isinstance(bundle, ForwardIntelligenceBundle):
            continue
        source_signal = _theme_signal(bundle)
        if source_signal is None:
            continue
        for symbol in _symbols(bundle):
            target_identifier = symbol_to_identifier.get(symbol)
            if target_identifier is None or target_identifier == bundle.candidate_identifier:
                continue
            sources_by_target.setdefault(target_identifier, []).append(
                (bundle.candidate_identifier, source_signal)
            )

    result: list[object] = []
    for context in contexts:
        target_identifier = str(getattr(context, "candidate_identifier"))
        bundle = getattr(context, "forward_intelligence", None)
        sources = sources_by_target.get(target_identifier, ())
        if not sources or not isinstance(bundle, ForwardIntelligenceBundle):
            result.append(context)
            continue
        target_candidate = candidate_by_identifier.get(target_identifier)
        if target_candidate is None:
            result.append(context)
            continue
        target_symbol = str(
            getattr(getattr(target_candidate, "instrument"), "symbol")
        ).upper()
        base_signals = tuple(
            item
            for item in bundle.signals
            if not item.identifier.startswith(_SIGNAL_PREFIX)
        )
        source_ids = tuple(dict.fromkeys(item[0] for item in sources))
        evidence_ids = tuple(
            dict.fromkeys(
                identifier
                for _source, signal in sources
                for identifier in signal.evidence_identifiers
            )
        )
        confidence = fmean(signal.confidence for _source, signal in sources)
        successor = ForwardSignal(
            identifier=f"{_SIGNAL_PREFIX}{target_identifier}",
            as_of=bundle.as_of,
            name="governed structural-theme next-beneficiary evidence",
            channels=("forecast", "fundamental"),
            expected_return_impact=0.0,
            confidence=confidence,
            evidence=(
                f"{target_symbol} is explicitly named as a next beneficiary by governed structural-theme transmission from {', '.join(source_ids)}.",
            ),
            contradictory_evidence=(),
            assumptions=(
                "The explicitly modeled theme transmission and bottleneck remain active through the stated lag",
                "Beneficiary status creates research priority only; candidate-specific economics must independently validate the opportunity",
            ),
            risks=(
                "The upstream theme can be correct while the named beneficiary fails to monetize the bottleneck",
                "Capacity, substitution, competition, valuation, or timing can eliminate the expected downstream benefit",
            ),
            change_conditions=(
                "Remove successor attention when the source theme no longer names the candidate, bottleneck conditions normalize, or candidate-specific evidence contradicts the transmission",
            ),
            evidence_identifiers=evidence_ids,
        )
        diagnostics = tuple(
            item
            for item in bundle.diagnostics
            if not item.startswith("Theme successor rotation:")
        ) + (
            "Theme successor rotation: "
            f"{target_symbol} <- {', '.join(source_ids)}; zero-return-impact research propagation.",
        )
        enriched = replace(
            bundle,
            signals=(*base_signals, successor),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            model_versions=tuple(dict.fromkeys((*bundle.model_versions, _POLICY_VERSION))),
        )
        result.append(replace(context, forward_intelligence=enriched))
    return tuple(result)


def theme_successor_score(bundle: object | None) -> tuple[float, tuple[str, ...]]:
    """Return attention score and lineage without changing expected return."""

    if not isinstance(bundle, ForwardIntelligenceBundle):
        return 0.0, ()
    markers = tuple(
        item for item in bundle.signals if item.identifier.startswith(_SIGNAL_PREFIX)
    )
    if not markers:
        return 0.0, ()
    return (
        max(item.confidence for item in markers),
        tuple(
            dict.fromkeys(
                identifier
                for item in markers
                for identifier in item.evidence_identifiers
            )
        ),
    )


__all__ = ["propagate_theme_successors", "theme_successor_score"]
