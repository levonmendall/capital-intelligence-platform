"""Strict production-context contract used by the scheduled canonical CIO cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from application.production_cio import (
    ProductionCanonicalCIOContext as _BaseProductionCanonicalCIOContext,
    ProductionCanonicalCIOContextProvider,
    ProductionCanonicalCIOExecutor as _BaseProductionCanonicalCIOExecutor,
)
from screening import candidate_from_payload


_LOGGER = logging.getLogger("capital_intelligence.persistent_cash")


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ProductionCanonicalCIOContext(_BaseProductionCanonicalCIOContext):
    """Complete official production briefing package for one CIO decision."""

    knowledge_cutoff: datetime | None = None
    process_version: str = "unknown"
    eligible_universe_publication_identifier: str = "unknown"

    def __post_init__(self) -> None:
        super(ProductionCanonicalCIOContext, self).__post_init__()
        cutoff = self.knowledge_cutoff or self.as_of
        object.__setattr__(
            self,
            "knowledge_cutoff",
            _aware(cutoff, field_name="knowledge_cutoff"),
        )
        object.__setattr__(
            self,
            "process_version",
            _required_text(self.process_version, field_name="process_version"),
        )
        object.__setattr__(
            self,
            "eligible_universe_publication_identifier",
            _required_text(
                self.eligible_universe_publication_identifier,
                field_name="eligible_universe_publication_identifier",
            ),
        )
        if cutoff > self.as_of:
            raise ValueError(
                "knowledge_cutoff cannot follow the decision timestamp"
            )
        if self.manifest is not None and self.manifest.knowledge_cutoff != cutoff:
            raise ValueError(
                "production context and manifest knowledge cutoffs do not match"
            )

    @property
    def decision_timestamp(self) -> datetime:
        return self.as_of


class ProductionCanonicalCIOExecutor(_BaseProductionCanonicalCIOExecutor):
    """Run the CIO only when persisted screening rankings remain unchanged."""

    def run(self, *, as_of: datetime):
        decision_time = _aware(as_of, field_name="as_of")
        if not self.screening_store.verify_integrity():
            raise RuntimeError(
                "complete-universe screening integrity is unavailable"
            )
        context = self.context_provider.load_context(as_of=decision_time)
        if not isinstance(context, _BaseProductionCanonicalCIOContext):
            raise TypeError(
                "context provider must return ProductionCanonicalCIOContext"
            )
        if context.as_of != decision_time:
            raise ValueError(
                "production context must share the scheduled decision timestamp"
            )
        publication = self.screening_store.publication(
            context.screening_cycle_identifier
        )
        if publication is None:
            raise RuntimeError(
                "canonical CIO cycle requires a persisted complete-universe "
                "publication"
            )
        if (
            publication.screened_instrument_count
            != publication.eligible_instrument_count
        ):
            raise RuntimeError(
                "canonical CIO cycle cannot consume partial universe coverage"
            )
        if (
            publication.opportunity_context_identifier
            != context.opportunity_context.identifier
        ):
            raise ValueError(
                "screening publication and opportunity context do not match"
            )
        candidates = tuple(
            candidate_from_payload(payload)
            for payload in publication.candidate_payloads
        )
        if any(item.as_of != decision_time for item in candidates):
            raise ValueError(
                "screening candidates must share the scheduled decision timestamp"
            )
        if len(candidates) != publication.candidate_count:
            raise RuntimeError(
                "screening publication candidate count does not reconcile"
            )

        ranked_payloads = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("ranked", ())
        )
        rejected_payloads = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("rejected", ())
        )
        qualified_identifiers = tuple(
            _required_text(
                item.get("candidate_identifier"),
                field_name="qualified candidate identifier",
            )
            for item in ranked_payloads
        )
        rejected_identifiers = tuple(
            _required_text(
                item.get("candidate_identifier"),
                field_name="rejected candidate identifier",
            )
            for item in rejected_payloads
        )
        context_identifiers = tuple(
            item.candidate_identifier for item in context.specialist_contexts
        )
        if set(context_identifiers) != set(qualified_identifiers):
            missing = sorted(
                set(qualified_identifiers) - set(context_identifiers)
            )
            extra = sorted(
                set(context_identifiers) - set(qualified_identifiers)
            )
            raise ValueError(
                "specialist context coverage must exactly match the persisted "
                f"qualified candidate set: missing={missing} extra={extra}"
            )

        if context.manifest is not None:
            if (
                context.manifest.screening_publication_identifier
                != publication.identifier
            ):
                raise ValueError(
                    "production context manifest does not match publication"
                )
            if (
                context.manifest.candidate_identifiers
                != qualified_identifiers
            ):
                raise ValueError(
                    "production context manifest candidate order does not match "
                    "the persisted opportunity queue"
                )

        governed_context = (
            isinstance(context, ProductionCanonicalCIOContext)
            and context.eligible_universe_publication_identifier != "unknown"
            and context.process_version != "unknown"
        )
        if governed_context:
            publication_identifiers = qualified_identifiers + rejected_identifiers
            candidate_identifiers = tuple(item.identifier for item in candidates)
            if set(publication_identifiers) != set(candidate_identifiers):
                missing = sorted(
                    set(candidate_identifiers) - set(publication_identifiers)
                )
                extra = sorted(
                    set(publication_identifiers) - set(candidate_identifiers)
                )
                raise ValueError(
                    "persisted opportunity queue must reconcile every screened "
                    f"candidate: missing={missing} extra={extra}"
                )
            runtime_queue = self.cycle.opportunity_engine.build_queue(
                candidates,
                context.opportunity_context,
            )
            runtime_ranked = tuple(
                item.candidate.identifier for item in runtime_queue.ranked
            )
            runtime_rejected = tuple(
                item.candidate_identifier for item in runtime_queue.rejected
            )
            persisted_policy = _required_text(
                publication.opportunity_queue_payload.get("policy_version"),
                field_name="persisted opportunity policy version",
            )
            if runtime_queue.policy_version != persisted_policy:
                raise ValueError(
                    "runtime opportunity policy version differs from the "
                    "persisted screening publication"
                )
            if runtime_ranked != qualified_identifiers:
                raise ValueError(
                    "runtime opportunity ranking differs from the completed "
                    "screening publication"
                )
            if runtime_rejected != rejected_identifiers:
                raise ValueError(
                    "runtime rejection set differs from the completed screening "
                    "publication"
                )

        portfolio = context.portfolio
        if governed_context:
            portfolio = replace(
                portfolio,
                eligible_universe_publication_identifier=(
                    context.eligible_universe_publication_identifier
                ),
            )
        prior_decision_contexts = ()
        active_theses = ()
        if self.cycle.journal is not None:
            prior_decision_contexts = self.cycle.journal.prior_decision_contexts(
                candidates,
                as_of=context.opportunity_context.as_of,
            )
            active_theses = self.cycle.journal.active_theses(
                candidates,
                as_of=context.opportunity_context.as_of,
            )
        result = self.cycle.run(
            identifier=context.identifier,
            candidates=candidates,
            opportunity_context=context.opportunity_context,
            specialist_contexts=context.specialist_contexts,
            portfolio=portfolio,
            prior_decision_contexts=prior_decision_contexts,
            active_theses=active_theses,
            code_version=context.code_version,
        )
        journal = self.cycle.journal
        if journal is not None:
            try:
                from evaluation.persistent_cash import (
                    append_persistent_cash_diagnostic,
                    build_persistent_cash_diagnostic,
                )

                diagnostic = build_persistent_cash_diagnostic(
                    publication=publication,
                    candidates=candidates,
                    context_candidate_identifiers=context_identifiers,
                    result=result,
                    cash_weight_before=portfolio.cash_weight,
                    minimum_evidence_score=(
                        self.cycle.opportunity_engine.policy.minimum_evidence_score
                    ),
                    minimum_evidence_dimension=(
                        self.cycle.opportunity_engine.policy.minimum_evidence_dimension
                    ),
                    code_version=context.code_version,
                )
                append_persistent_cash_diagnostic(journal, diagnostic)
            except Exception:
                _LOGGER.exception(
                    "persistent-cash diagnostic failed after canonical CIO cycle %s; "
                    "the non-authoritative diagnostic cannot alter the cycle result",
                    context.identifier,
                )
        return result


__all__ = [
    "ProductionCanonicalCIOContext",
    "ProductionCanonicalCIOContextProvider",
    "ProductionCanonicalCIOExecutor",
]
