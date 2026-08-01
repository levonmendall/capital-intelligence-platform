"""Immutable opportunity-context and queue snapshots.

A screening publication freezes the exact point-in-time alternatives and preliminary
qualification queue.  Before specialist analysis, the production executor freezes the
portfolio-ranked decision queue as a child snapshot.  Later code may validate these
objects, but it may not silently reinterpret an older publication with newer policy.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cio import CandidateDecisionRecord, UniverseAssessment, UniverseDisposition
from governance.asset_class_scope import AssetClassApprovalState
from opportunity.models import (
    AnalysisLane,
    AlternativeKind,
    AlternativeUse,
    CandidateQualification,
    OpportunityQueue,
    OpportunityRankingInput,
    OpportunitySetContext,
    QualificationOutcome,
    RankedOpportunity,
    ScoreComponent,
)


SNAPSHOT_SCHEMA_VERSION = "opportunity-snapshot.v1"
PUBLICATION_SNAPSHOT_KIND = "publication"
DECISION_SNAPSHOT_KIND = "decision"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} cannot be empty")
    return result


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("opportunity snapshot must contain finite canonical JSON") from error


def _content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _code_version(value: str | None) -> str:
    return _required_text(
        value
        or os.getenv("CAPITAL_INTELLIGENCE_CODE_VERSION")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown",
        field_name="code_version",
    )


def _alternative_payload(item: AlternativeUse) -> dict[str, Any]:
    return {
        "identifier": item.identifier,
        "kind": item.kind.value,
        "expected_return": item.expected_return,
        "implementation_cost_return": item.implementation_cost_return,
        "net_expected_return": item.net_expected_return,
        "evidence_quality": item.evidence_quality,
        "liquidity_score": item.liquidity_score,
        "current_weight": item.current_weight,
    }


def _ranking_payload(item: OpportunityRankingInput) -> dict[str, Any]:
    return {
        "candidate_identifier": item.candidate_identifier,
        "marginal_portfolio_contribution": item.marginal_portfolio_contribution,
        "diversification_score": item.diversification_score,
        "thesis_clarity_score": item.thesis_clarity_score,
        "invalidation_clarity_score": item.invalidation_clarity_score,
        "forecast_durability_score": item.forecast_durability_score,
    }


def _universe_payload(item: UniverseAssessment) -> dict[str, Any]:
    return {
        "instrument_id": item.instrument_id,
        "disposition": item.disposition.value,
        "policy_version": item.policy_version,
        "reasons": list(item.reasons),
        "asset_class_approval_identifier": item.asset_class_approval_identifier,
        "asset_class_approval_state": (
            None
            if item.asset_class_approval_state is None
            else item.asset_class_approval_state.value
        ),
        "asset_class_policy_version": item.asset_class_policy_version,
    }


def _qualification_payload(item: CandidateQualification) -> dict[str, Any]:
    return {
        "candidate_identifier": item.candidate_identifier,
        "outcome": item.outcome.value,
        "policy_version": item.policy_version,
        "universe": _universe_payload(item.universe),
        "effective_opportunity_cost": item.effective_opportunity_cost,
        "opportunity_edge": item.opportunity_edge,
        "reasons": list(item.reasons),
        "analysis_lane": item.analysis_lane.value,
        "best_alternative_identifier": item.best_alternative_identifier,
        "best_alternative_kind": (
            None
            if item.best_alternative_kind is None
            else item.best_alternative_kind.value
        ),
        "baseline_alternative_identifier": item.baseline_alternative_identifier,
        "baseline_opportunity_cost": item.baseline_opportunity_cost,
        "resolved_policy_profile": item.resolved_policy_profile,
    }


def _component_payload(item: ScoreComponent) -> dict[str, Any]:
    return {
        "name": item.name,
        "raw_value": item.raw_value,
        "normalized_score": item.normalized_score,
        "weight": item.weight,
        "contribution": item.contribution,
    }


def _queue_payload(queue: OpportunityQueue) -> dict[str, Any]:
    return {
        "context_identifier": queue.context_identifier,
        "policy_version": queue.policy_version,
        "ranked": [
            {
                "rank": item.rank,
                "candidate_identifier": item.candidate.identifier,
                "qualification": _qualification_payload(item.qualification),
                "score": item.score,
                "components": [
                    _component_payload(component) for component in item.components
                ],
            }
            for item in queue.ranked
        ],
        "rejected": [
            _qualification_payload(item) for item in queue.rejected
        ],
    }


def _context_payload(context: OpportunitySetContext) -> dict[str, Any]:
    return {
        "identifier": context.identifier,
        "as_of": context.as_of.isoformat(),
        "alternatives": [
            _alternative_payload(item) for item in context.alternatives
        ],
        "ranking_inputs": [
            _ranking_payload(item) for item in context.ranking_inputs
        ],
    }


@dataclass(frozen=True, slots=True)
class OpportunitySnapshot:
    snapshot_kind: str
    created_at: datetime
    code_version: str
    opportunity_policy_version: str
    robustness_policy_version: str
    policy_matrix_version: str
    universe_policy_version: str
    context: OpportunitySetContext
    queue: OpportunityQueue
    content_hash: str
    parent_snapshot_hash: str | None = None
    screening_publication_identifier: str | None = None

    def __post_init__(self) -> None:
        if self.snapshot_kind not in {
            PUBLICATION_SNAPSHOT_KIND,
            DECISION_SNAPSHOT_KIND,
        }:
            raise ValueError("unsupported opportunity snapshot kind")
        _aware(self.created_at, field_name="created_at")
        for field_name in (
            "code_version",
            "opportunity_policy_version",
            "robustness_policy_version",
            "policy_matrix_version",
            "universe_policy_version",
            "content_hash",
        ):
            _required_text(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.context, OpportunitySetContext):
            raise TypeError("context must be OpportunitySetContext")
        if not isinstance(self.queue, OpportunityQueue):
            raise TypeError("queue must be OpportunityQueue")
        if self.queue.context_identifier != self.context.identifier:
            raise ValueError("snapshot queue and context identifiers do not match")
        if self.parent_snapshot_hash is not None:
            _required_text(self.parent_snapshot_hash, field_name="parent_snapshot_hash")
        if self.screening_publication_identifier is not None:
            _required_text(
                self.screening_publication_identifier,
                field_name="screening_publication_identifier",
            )


def build_opportunity_snapshot(
    *,
    snapshot_kind: str,
    context: OpportunitySetContext,
    queue: OpportunityQueue,
    engine: object,
    created_at: datetime,
    code_version: str | None = None,
    parent_snapshot_hash: str | None = None,
    screening_publication_identifier: str | None = None,
) -> dict[str, Any]:
    if snapshot_kind not in {PUBLICATION_SNAPSHOT_KIND, DECISION_SNAPSHOT_KIND}:
        raise ValueError("unsupported opportunity snapshot kind")
    if not isinstance(context, OpportunitySetContext):
        raise TypeError("context must be OpportunitySetContext")
    if not isinstance(queue, OpportunityQueue):
        raise TypeError("queue must be OpportunityQueue")
    if queue.context_identifier != context.identifier:
        raise ValueError("queue and context identifiers do not match")
    created = _aware(created_at, field_name="created_at")
    policy = getattr(engine, "policy", None)
    robust_assessor = getattr(engine, "robust_assessor", None)
    robust_policy = getattr(robust_assessor, "policy", None)
    policy_matrix = getattr(engine, "policy_matrix", None)
    universe_policy = getattr(engine, "universe_policy", None)
    core: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_kind": snapshot_kind,
        "created_at": created.isoformat(),
        "code_version": _code_version(code_version),
        "opportunity_policy_version": _required_text(
            getattr(policy, "version", queue.policy_version),
            field_name="opportunity_policy_version",
        ),
        "robustness_policy_version": _required_text(
            getattr(robust_policy, "version", "unknown"),
            field_name="robustness_policy_version",
        ),
        "policy_matrix_version": _required_text(
            getattr(policy_matrix, "version", "unknown"),
            field_name="policy_matrix_version",
        ),
        "universe_policy_version": _required_text(
            getattr(universe_policy, "version", "unknown"),
            field_name="universe_policy_version",
        ),
        "parent_snapshot_hash": parent_snapshot_hash,
        "screening_publication_identifier": screening_publication_identifier,
        "context": _context_payload(context),
        "queue": _queue_payload(queue),
    }
    return {**core, "content_hash": _content_hash(core)}


def _alternative_from_payload(payload: Mapping[str, Any]) -> AlternativeUse:
    item = AlternativeUse(
        identifier=str(payload["identifier"]),
        kind=AlternativeKind(str(payload["kind"])),
        expected_return=float(payload["expected_return"]),
        implementation_cost_return=float(payload["implementation_cost_return"]),
        evidence_quality=float(payload["evidence_quality"]),
        liquidity_score=float(payload["liquidity_score"]),
        current_weight=float(payload.get("current_weight", 0.0)),
    )
    if abs(item.net_expected_return - float(payload["net_expected_return"])) > 1e-8:
        raise ValueError("snapshot alternative net return is inconsistent")
    return item


def _ranking_from_payload(payload: Mapping[str, Any]) -> OpportunityRankingInput:
    return OpportunityRankingInput(
        candidate_identifier=str(payload["candidate_identifier"]),
        marginal_portfolio_contribution=float(
            payload["marginal_portfolio_contribution"]
        ),
        diversification_score=float(payload["diversification_score"]),
        thesis_clarity_score=float(payload["thesis_clarity_score"]),
        invalidation_clarity_score=float(payload["invalidation_clarity_score"]),
        forecast_durability_score=float(payload["forecast_durability_score"]),
    )


def _universe_from_payload(payload: Mapping[str, Any]) -> UniverseAssessment:
    raw_state = payload.get("asset_class_approval_state")
    return UniverseAssessment(
        instrument_id=str(payload["instrument_id"]),
        disposition=UniverseDisposition(str(payload["disposition"])),
        policy_version=str(payload["policy_version"]),
        reasons=tuple(str(item) for item in payload["reasons"]),
        asset_class_approval_identifier=(
            None
            if payload.get("asset_class_approval_identifier") is None
            else str(payload["asset_class_approval_identifier"])
        ),
        asset_class_approval_state=(
            None if raw_state is None else AssetClassApprovalState(str(raw_state))
        ),
        asset_class_policy_version=(
            None
            if payload.get("asset_class_policy_version") is None
            else str(payload["asset_class_policy_version"])
        ),
    )


def _qualification_from_payload(
    payload: Mapping[str, Any],
) -> CandidateQualification:
    raw_best_kind = payload.get("best_alternative_kind")
    return CandidateQualification(
        candidate_identifier=str(payload["candidate_identifier"]),
        outcome=QualificationOutcome(str(payload["outcome"])),
        policy_version=str(payload["policy_version"]),
        universe=_universe_from_payload(dict(payload["universe"])),
        effective_opportunity_cost=float(payload["effective_opportunity_cost"]),
        opportunity_edge=float(payload["opportunity_edge"]),
        reasons=tuple(str(item) for item in payload["reasons"]),
        analysis_lane=AnalysisLane(str(payload["analysis_lane"])),
        best_alternative_identifier=(
            None
            if payload.get("best_alternative_identifier") is None
            else str(payload["best_alternative_identifier"])
        ),
        best_alternative_kind=(
            None if raw_best_kind is None else AlternativeKind(str(raw_best_kind))
        ),
        baseline_alternative_identifier=(
            None
            if payload.get("baseline_alternative_identifier") is None
            else str(payload["baseline_alternative_identifier"])
        ),
        baseline_opportunity_cost=(
            None
            if payload.get("baseline_opportunity_cost") is None
            else float(payload["baseline_opportunity_cost"])
        ),
        resolved_policy_profile=(
            None
            if payload.get("resolved_policy_profile") is None
            else str(payload["resolved_policy_profile"])
        ),
    )


def _component_from_payload(payload: Mapping[str, Any]) -> ScoreComponent:
    item = ScoreComponent(
        name=str(payload["name"]),
        raw_value=float(payload["raw_value"]),
        normalized_score=float(payload["normalized_score"]),
        weight=float(payload["weight"]),
    )
    if abs(item.contribution - float(payload["contribution"])) > 1e-8:
        raise ValueError("snapshot score component contribution is inconsistent")
    return item


def load_opportunity_snapshot(
    payload: Mapping[str, Any],
    *,
    candidates: Mapping[str, CandidateDecisionRecord],
) -> OpportunitySnapshot:
    if not isinstance(payload, Mapping):
        raise TypeError("opportunity snapshot payload must be a mapping")
    raw = dict(payload)
    content_hash = _required_text(raw.pop("content_hash", None), field_name="content_hash")
    if raw.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported opportunity snapshot schema")
    if _content_hash(raw) != content_hash:
        raise ValueError("opportunity snapshot content hash is invalid")

    context_payload = dict(raw["context"])
    context = OpportunitySetContext(
        identifier=str(context_payload["identifier"]),
        as_of=datetime.fromisoformat(str(context_payload["as_of"])),
        alternatives=tuple(
            _alternative_from_payload(dict(item))
            for item in context_payload["alternatives"]
        ),
        ranking_inputs=tuple(
            _ranking_from_payload(dict(item))
            for item in context_payload.get("ranking_inputs", ())
        ),
    )
    queue_payload = dict(raw["queue"])
    ranked: list[RankedOpportunity] = []
    for item in queue_payload["ranked"]:
        item_payload = dict(item)
        candidate_identifier = str(item_payload["candidate_identifier"])
        candidate = candidates.get(candidate_identifier)
        if candidate is None:
            raise ValueError(
                f"snapshot references unknown candidate {candidate_identifier}"
            )
        ranked.append(
            RankedOpportunity(
                rank=int(item_payload["rank"]),
                candidate=candidate,
                qualification=_qualification_from_payload(
                    dict(item_payload["qualification"])
                ),
                score=float(item_payload["score"]),
                components=tuple(
                    _component_from_payload(dict(component))
                    for component in item_payload["components"]
                ),
            )
        )
    rejected = tuple(
        _qualification_from_payload(dict(item))
        for item in queue_payload["rejected"]
    )
    queue = OpportunityQueue(
        context_identifier=str(queue_payload["context_identifier"]),
        policy_version=str(queue_payload["policy_version"]),
        ranked=tuple(ranked),
        rejected=rejected,
    )
    represented = {
        *(item.candidate.identifier for item in queue.ranked),
        *(item.candidate_identifier for item in queue.rejected),
    }
    if represented != set(candidates):
        raise ValueError("snapshot candidate coverage is incomplete or contains extras")
    return OpportunitySnapshot(
        snapshot_kind=str(raw["snapshot_kind"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        code_version=str(raw["code_version"]),
        opportunity_policy_version=str(raw["opportunity_policy_version"]),
        robustness_policy_version=str(raw["robustness_policy_version"]),
        policy_matrix_version=str(raw["policy_matrix_version"]),
        universe_policy_version=str(raw["universe_policy_version"]),
        context=context,
        queue=queue,
        content_hash=content_hash,
        parent_snapshot_hash=(
            None
            if raw.get("parent_snapshot_hash") is None
            else str(raw["parent_snapshot_hash"])
        ),
        screening_publication_identifier=(
            None
            if raw.get("screening_publication_identifier") is None
            else str(raw["screening_publication_identifier"])
        ),
    )


__all__ = [
    "DECISION_SNAPSHOT_KIND",
    "OpportunitySnapshot",
    "PUBLICATION_SNAPSHOT_KIND",
    "SNAPSHOT_SCHEMA_VERSION",
    "build_opportunity_snapshot",
    "load_opportunity_snapshot",
]
