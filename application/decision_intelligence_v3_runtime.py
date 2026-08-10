"""Post-cycle Decision Intelligence v3 persistence binding.

This runtime is intentionally downstream of the authoritative CIO and construction
cycle. Failure to write an explanation/measurement packet is logged by the caller and
can never alter the already-computed CIO decision or canonical portfolio state.
Expectation forecasts are registered from the same packet the CIO produced so later
resolution measures the exact point-in-time expectation rather than a reconstruction.
A whole-portfolio factor/stress synthesis is also persisted downstream; it is read-only
and may influence construction only after separate analytical-promotion certification.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from evaluation.decision_intelligence_v3 import SQLiteDecisionIntelligenceV3Store
from evaluation.expectations_resolution import (
    ExpectationsForecastRecord,
    SQLiteExpectationsResolutionStore,
)
from evaluation.portfolio_risk_synthesis import SQLitePortfolioRiskSynthesisStore
from intelligence.decision_intelligence_v3 import (
    build_candidate_decision_intelligence_packet,
)
from intelligence.portfolio_risk_synthesis import build_portfolio_risk_synthesis

_LOGGER = logging.getLogger("capital_intelligence.decision_intelligence_learning")


def _by_candidate(values: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in tuple(values or ()):
        identifier = str(getattr(item, "candidate_identifier", "")).strip()
        if identifier:
            result[identifier] = item
    return result


def _joint_for_candidate(values: object, candidate_identifier: str):
    for item in tuple(values or ()):
        direct = str(getattr(item, "candidate_identifier", "")).strip()
        if direct == candidate_identifier:
            return item
        identifiers = tuple(
            str(value).strip()
            for value in tuple(getattr(item, "candidate_identifiers", ()) or ())
        )
        if candidate_identifier in identifiers:
            return item
    return None


def _thesis_for_candidate(values: object, candidate_identifier: str):
    for item in tuple(values or ()):
        for name in ("candidate_identifier", "asset_identifier", "identifier"):
            value = str(getattr(item, name, "")).strip()
            if value == candidate_identifier:
                return item
    return None


def _database_path() -> Path:
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_DECISION_INTELLIGENCE_V3_DB",
            "database/decision-intelligence-v3.db",
        )
    ).expanduser()


def _expectations_database_path() -> Path:
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_EXPECTATIONS_RESOLUTION_DB",
            "database/expectations-resolution.db",
        )
    ).expanduser()


def _risk_database_path() -> Path:
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_PORTFOLIO_RISK_SYNTHESIS_DB",
            "database/portfolio-risk-synthesis.db",
        )
    ).expanduser()


def append_post_cycle_decision_intelligence(
    *,
    result: object,
    context: object,
    path: str | Path | None = None,
) -> tuple[str, ...]:
    """Persist read-only decision, expectations, and portfolio-risk evidence."""

    if result is None or context is None:
        return ()
    cycle_identifier = str(getattr(result, "identifier", "")).strip()
    if not cycle_identifier:
        raise ValueError("cycle result must have an identifier")

    ranked = tuple(getattr(getattr(result, "opportunity_queue"), "ranked", ()) or ())
    candidates = {
        str(getattr(getattr(item, "candidate"), "identifier")): getattr(item, "candidate")
        for item in ranked
    }
    contexts = _by_candidate(getattr(context, "specialist_contexts", ()))
    decisions = tuple(getattr(result, "decisions", ()) or ())
    risk = _by_candidate(getattr(result, "risk_assessments", ()))
    snapshots = _by_candidate(getattr(result, "evaluation_snapshots", ()))
    joint = tuple(getattr(result, "joint_candidate_assessments", ()) or ())
    theses = tuple(getattr(result, "theses", ()) or ())
    portfolio = getattr(context, "portfolio")
    construction = getattr(result, "construction", None)

    store = SQLiteDecisionIntelligenceV3Store(path or _database_path())
    expectations_store = SQLiteExpectationsResolutionStore(
        _expectations_database_path()
    )
    hashes: list[str] = []
    for decision in decisions:
        candidate_identifier = str(
            getattr(decision, "candidate_identifier", "")
        ).strip()
        candidate = candidates.get(candidate_identifier)
        specialist_context = contexts.get(candidate_identifier)
        if candidate is None or specialist_context is None:
            # The canonical cycle itself owns coverage validation. The downstream
            # read model must never infer a candidate/context that was not present.
            continue
        packet = build_candidate_decision_intelligence_packet(
            cycle_identifier=cycle_identifier,
            candidate=candidate,
            specialist_context=specialist_context,
            portfolio=portfolio,
            decision=decision,
            construction=construction,
            risk_assessment=risk.get(candidate_identifier),
            joint_assessment=_joint_for_candidate(joint, candidate_identifier),
            thesis=_thesis_for_candidate(theses, candidate_identifier),
            evaluation_snapshot=snapshots.get(candidate_identifier),
        )
        hashes.append(store.append_packet(packet))
        forecast = ExpectationsForecastRecord.from_packet(packet)
        if forecast is not None:
            try:
                expectations_store.append_forecast(forecast)
            except Exception:
                # Expectations resolution is an empirical-learning sidecar. A
                # persistence defect cannot invalidate the canonical packet or CIO
                # result; the operational log makes the coverage loss visible.
                _LOGGER.exception(
                    "expectations forecast registration failed for %s",
                    packet.identifier,
                )

    try:
        risk_synthesis = build_portfolio_risk_synthesis(
            portfolio=portfolio,
            construction=construction,
            candidates=tuple(candidates.values()),
        )
        SQLitePortfolioRiskSynthesisStore(_risk_database_path()).append(
            risk_synthesis
        )
    except Exception:
        # Same governance boundary as expectations resolution: this is downstream
        # empirical/diagnostic state and cannot invalidate the authoritative CIO or
        # construction result. Missing dynamic histories remain explicitly unavailable.
        _LOGGER.exception(
            "portfolio risk synthesis persistence failed for %s",
            cycle_identifier,
        )
    return tuple(hashes)


__all__ = ["append_post_cycle_decision_intelligence"]
