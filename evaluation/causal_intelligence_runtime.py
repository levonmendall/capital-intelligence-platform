"""Downstream persistence of governed causal assessments.

This sidecar stores the exact causal assessments produced by the event-forward bridge.
It is intentionally downstream of event qualification and cannot change candidate
eligibility, specialist evidence, CIO conclusions, or portfolio construction.
"""
from __future__ import annotations

import os
from pathlib import Path

from evaluation.causal_intelligence_graph import (
    SQLiteCausalIntelligenceGraphStore,
    build_causal_investment_graph,
)


def _path() -> Path:
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_CAUSAL_INTELLIGENCE_DB",
            "database/causal-intelligence-graph.db",
        )
    ).expanduser()


def persist_governed_event_forward_result(
    result: object,
    *,
    path: str | Path | None = None,
) -> tuple[str, ...]:
    """Persist every retained assessment with its canonical candidate mappings."""

    assessments = tuple(getattr(result, "assessments", ()) or ())
    if not assessments:
        return ()
    raw_links = tuple(getattr(result, "candidate_exposure_links", ()) or ())
    links_by_assessment: dict[str, list[tuple[str, str]]] = {}
    for assessment_identifier, target_identifier, candidate_identifier in raw_links:
        links_by_assessment.setdefault(str(assessment_identifier), []).append(
            (str(target_identifier), str(candidate_identifier))
        )
    store = SQLiteCausalIntelligenceGraphStore(path or _path())
    hashes = []
    for assessment in assessments:
        graph = build_causal_investment_graph(
            assessment,
            candidate_exposure_links=tuple(
                dict.fromkeys(links_by_assessment.get(assessment.identifier, ()))
            ),
        )
        hashes.append(store.append_graph(graph))
    return tuple(hashes)


__all__ = ["persist_governed_event_forward_result"]
