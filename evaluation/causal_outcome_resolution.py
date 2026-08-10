"""Point-in-time guarded causal outcome resolution."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from evaluation.causal_intelligence_graph import (
    CausalTransmissionOutcome,
    SQLiteCausalIntelligenceGraphStore,
)


class CausalOutcomeResolutionError(ValueError):
    pass


def _edge(store: SQLiteCausalIntelligenceGraphStore, edge_identifier: str) -> dict[str, Any] | None:
    connection = sqlite3.connect(store.path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT payload_json FROM causal_graphs ORDER BY sequence ASC"
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        graph = json.loads(str(row["payload_json"]))
        for edge in graph.get("edges", ()):
            if str(edge.get("identifier", "")) == edge_identifier:
                return dict(edge)
    return None


def append_point_in_time_causal_outcome(
    store: SQLiteCausalIntelligenceGraphStore,
    outcome: CausalTransmissionOutcome,
) -> str:
    if not isinstance(store, SQLiteCausalIntelligenceGraphStore):
        raise TypeError("store must be SQLiteCausalIntelligenceGraphStore")
    if not isinstance(outcome, CausalTransmissionOutcome):
        raise TypeError("outcome must be CausalTransmissionOutcome")
    edge = _edge(store, outcome.edge_identifier)
    if edge is None:
        raise CausalOutcomeResolutionError("causal outcome references an unknown predicted edge")
    if str(edge.get("relationship", "")) != "transmits_to":
        raise CausalOutcomeResolutionError("only predicted transmission edges can receive causal outcomes")
    predicted_at = datetime.fromisoformat(str(edge["as_of"]))
    if outcome.observed_at <= predicted_at:
        raise CausalOutcomeResolutionError(
            "causal outcome must be observed strictly after the predicted transmission"
        )
    return store.append_outcome(outcome)


__all__ = ["CausalOutcomeResolutionError", "append_point_in_time_causal_outcome"]
