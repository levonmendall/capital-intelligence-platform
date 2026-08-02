"""Runtime executor binding CIO authority to registry-certified instruments."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from application import production_context_contract as contract
from governance.bounded_pilot_scope import BoundedPilotCapabilityAuthority
from governance.market_participation import CanonicalMarketParticipationAuthority
from opportunity import OpportunityEngine, OpportunityQueue, RankedOpportunity
from opportunity.snapshot import (
    PUBLICATION_SNAPSHOT_KIND,
    load_opportunity_snapshot,
)
from operations.active_paper_universe import load_active_paper_universe_for_publication
from screening import candidate_from_payload


_AUTHORITY_BINDING_LOCK = threading.RLock()
_ORIGINAL_MARKER = "_canonical_market_registry_original_from_universe"


def _install_registry_bounded_authority() -> None:
    """Ensure every production authority build applies the market registry first."""

    existing = getattr(BoundedPilotCapabilityAuthority, _ORIGINAL_MARKER, None)
    if existing is not None:
        return
    original = BoundedPilotCapabilityAuthority.from_universe.__func__
    setattr(BoundedPilotCapabilityAuthority, _ORIGINAL_MARKER, original)

    def from_registry(cls, universe, *, research_only: bool = False):
        filtered = (
            CanonicalMarketParticipationAuthority.load()
            .decision_authority_universe(universe)
        )
        return original(cls, filtered, research_only=research_only)

    BoundedPilotCapabilityAuthority.from_universe = classmethod(from_registry)


_install_registry_bounded_authority()


class _CachedContextProvider:
    def __init__(self, delegate, context, *, as_of: datetime) -> None:
        self._delegate = delegate
        self._context = context
        self._as_of = as_of

    @property
    def code_version(self):
        return getattr(self._delegate, "code_version", None)

    def load_context(self, *, as_of: datetime):
        if as_of != self._as_of:
            raise ValueError("cached context requested for another timestamp")
        return self._context


def _publication_and_candidates(executor, *, context):
    publication = executor.screening_store.publication(
        context.screening_cycle_identifier
    )
    if publication is None:
        raise RuntimeError(
            "canonical CIO cycle requires a persisted complete-universe publication"
        )
    candidates = tuple(
        candidate_from_payload(payload)
        for payload in publication.candidate_payloads
    )
    return publication, candidates



def _active_universe_path(executor) -> Path | None:
    provider = getattr(executor, "context_provider", None)
    visited: set[int] = set()
    while provider is not None and id(provider) not in visited:
        visited.add(id(provider))
        store = getattr(provider, "portfolio_store", None)
        path = getattr(store, "path", None)
        if path is not None:
            return Path(path).expanduser().with_name("active-paper-universe.json")
        provider = getattr(provider, "_delegate", None) or getattr(
            provider, "_stored_provider", None
        )
    return None

def _candidate_authority_universe(executor, *, context):
    _publication, candidates = _publication_and_candidates(
        executor,
        context=context,
    )
    expected_publication_identifier = str(
        getattr(context, "eligible_universe_publication_identifier", "")
    ).strip()
    if not expected_publication_identifier:
        raise RuntimeError(
            "runtime authority requires the exact eligible-universe publication identifier"
        )
    active = load_active_paper_universe_for_publication(
        expected_publication_identifier,
        path=_active_universe_path(executor),
    )
    # Research-only screening candidates may intentionally lack execution capability.
    # The exact active publication remains the sole source of paper authority; the
    # screening payload cannot manufacture an executable instrument.
    return SimpleNamespace(
        identifier=active.identifier,
        expected_publication_identifier=expected_publication_identifier,
        instruments=active.instruments,
        limitations=active.limitations,
    )


def _publication_snapshot(executor, *, context):
    if getattr(context, "opportunity_snapshot_hash", None) is None:
        return None
    publication, candidates = _publication_and_candidates(
        executor,
        context=context,
    )
    raw_snapshot = publication.opportunity_queue_payload.get(
        "opportunity_context_snapshot"
    )
    if not isinstance(raw_snapshot, dict):
        raise RuntimeError(
            "screening publication lacks an immutable opportunity snapshot"
        )
    candidate_map = {item.identifier: item for item in candidates}
    snapshot = load_opportunity_snapshot(
        raw_snapshot,
        candidates=candidate_map,
    )
    if snapshot.snapshot_kind != PUBLICATION_SNAPSHOT_KIND:
        raise RuntimeError("screening publication opportunity snapshot kind is invalid")
    if snapshot.content_hash != context.opportunity_snapshot_hash:
        raise RuntimeError(
            "screening publication opportunity snapshot hash does not match context"
        )
    if snapshot.screening_publication_identifier != publication.identifier:
        raise RuntimeError(
            "screening publication opportunity snapshot belongs to another publication"
        )
    return snapshot


def _rerank_persisted_membership(
    engine: OpportunityEngine,
    candidates,
    decision_context,
    publication_queue: OpportunityQueue,
) -> OpportunityQueue:
    """Apply portfolio diagnostics only to ordering, never qualification membership.

    ``OpportunityRankingInput`` is explicitly an ordering contract. Re-running
    qualification after publication can reinterpret an immutable candidate set and
    silently eject a previously certified candidate. Preserve the publication's
    qualified/rejected membership and qualifications, while recalculating only the
    disclosed ranking components and order with current-cycle portfolio diagnostics.
    """

    candidate_map = {item.identifier: item for item in candidates}
    represented = {
        *(item.candidate.identifier for item in publication_queue.ranked),
        *(item.candidate_identifier for item in publication_queue.rejected),
    }
    if represented != set(candidate_map):
        raise ValueError(
            "immutable publication queue does not cover the runtime candidate set"
        )

    rows = []
    for persisted in publication_queue.ranked:
        candidate = candidate_map[persisted.candidate.identifier]
        qualification = persisted.qualification
        robustness = engine.robustness(candidate, decision_context)
        components = engine._components(  # package-internal ranking rule
            candidate,
            qualification,
            robustness,
            decision_context,
        )
        score = round(sum(item.contribution for item in components), 8)
        rows.append(
            (
                candidate,
                qualification,
                components,
                score,
                robustness,
            )
        )

    rows.sort(
        key=lambda item: (
            1 if item[1].mandatory_holding_review else 0,
            item[3],
            item[4].stressed_edge,
            item[4].robust_edge,
            item[4].annualized_geometric_return,
            item[0].evidence_quality.score,
            item[0].instrument.symbol,
        ),
        reverse=True,
    )
    ranked = tuple(
        RankedOpportunity(
            rank=index,
            candidate=candidate,
            qualification=qualification,
            score=score,
            components=components,
        )
        for index, (
            candidate,
            qualification,
            components,
            score,
            _robustness,
        ) in enumerate(rows, start=1)
    )
    return OpportunityQueue(
        context_identifier=decision_context.identifier,
        policy_version=publication_queue.policy_version,
        ranked=ranked,
        rejected=publication_queue.rejected,
    )


class ProductionCanonicalCIOExecutor(contract.ProductionCanonicalCIOExecutor):
    """Requalify using exact registry-certified paper authority."""

    def run(self, *, as_of: datetime):
        original_provider = self.context_provider
        context = original_provider.load_context(as_of=as_of)
        governed_context = (
            str(
                getattr(
                    context,
                    "eligible_universe_publication_identifier",
                    "unknown",
                )
            ).strip()
            not in {"", "unknown"}
            and str(getattr(context, "process_version", "unknown")).strip()
            not in {"", "unknown"}
        )
        if not governed_context:
            # Legacy/rehearsal contexts have no execution publication and therefore
            # cannot receive dynamic paper authority. Preserve their analysis-only
            # test path without inventing a static execution fallback.
            return super().run(as_of=as_of)
        authority_universe = _candidate_authority_universe(self, context=context)
        publication_snapshot = _publication_snapshot(self, context=context)
        expected_publication_identifier = (
            authority_universe.expected_publication_identifier
        )

        def load_exact_authority(requested_identifier: str):
            requested = str(requested_identifier).strip()
            if not requested:
                raise ValueError("runtime authority publication identifier is empty")
            if (
                expected_publication_identifier is not None
                and requested != expected_publication_identifier
            ):
                raise ValueError(
                    "runtime authority request does not match certified publication"
                )
            return authority_universe

        original_build_queue = OpportunityEngine.build_queue

        def build_queue_with_immutable_membership(
            engine,
            candidates,
            opportunity_context,
        ):
            if (
                publication_snapshot is not None
                and opportunity_context.identifier
                == publication_snapshot.context.identifier
                and opportunity_context.alternatives
                == publication_snapshot.context.alternatives
                and opportunity_context.ranking_inputs
            ):
                return _rerank_persisted_membership(
                    engine,
                    candidates,
                    opportunity_context,
                    publication_snapshot.queue,
                )
            return original_build_queue(engine, candidates, opportunity_context)

        with _AUTHORITY_BINDING_LOCK:
            original_loader = contract.load_active_paper_universe_for_publication
            contract.load_active_paper_universe_for_publication = load_exact_authority
            OpportunityEngine.build_queue = build_queue_with_immutable_membership
            self.context_provider = _CachedContextProvider(
                original_provider, context, as_of=as_of
            )
            try:
                return super().run(as_of=as_of)
            finally:
                self.context_provider = original_provider
                OpportunityEngine.build_queue = original_build_queue
                contract.load_active_paper_universe_for_publication = original_loader


__all__ = ["ProductionCanonicalCIOExecutor"]
