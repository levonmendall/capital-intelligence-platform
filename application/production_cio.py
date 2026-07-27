"""Production executor for the canonical CIO decision cycle.

The executor binds the scheduled decision process to one complete-universe
screening publication.  External adapters may provide specialist and portfolio
context, but they cannot replace the candidate set or bypass the immutable
screening evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from application.cio_cycle import (
    CandidateCycleContext,
    CanonicalCIOCycle,
    CanonicalCIOCycleResult,
    CyclePortfolioState,
)
from opportunity import OpportunitySetContext
from screening import (
    SQLiteFullUniverseScreeningStore,
    candidate_from_payload,
)


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
class ProductionCanonicalCIOContext:
    """Non-candidate inputs required to execute one canonical CIO cycle."""

    identifier: str
    screening_cycle_identifier: str
    opportunity_context: OpportunitySetContext
    specialist_contexts: tuple[CandidateCycleContext, ...]
    portfolio: CyclePortfolioState
    code_version: str = "unknown"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "screening_cycle_identifier",
            "code_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.opportunity_context, OpportunitySetContext):
            raise TypeError("opportunity_context must be OpportunitySetContext")
        if not isinstance(self.specialist_contexts, tuple) or not all(
            isinstance(item, CandidateCycleContext)
            for item in self.specialist_contexts
        ):
            raise TypeError(
                "specialist_contexts must contain CandidateCycleContext values"
            )
        if not isinstance(self.portfolio, CyclePortfolioState):
            raise TypeError("portfolio must be CyclePortfolioState")
        if self.opportunity_context.as_of != self.portfolio.as_of:
            raise ValueError(
                "opportunity context and portfolio must share the decision timestamp"
            )

    @property
    def as_of(self) -> datetime:
        return self.portfolio.as_of


@runtime_checkable
class ProductionCanonicalCIOContextProvider(Protocol):
    """Adapter that supplies point-in-time specialist and portfolio context."""

    @property
    def name(self) -> str: ...

    def load_context(
        self,
        *,
        as_of: datetime,
    ) -> ProductionCanonicalCIOContext: ...


class ProductionCanonicalCIOExecutor:
    """Execute ``CanonicalCIOCycle`` from one immutable screening publication."""

    def __init__(
        self,
        *,
        cycle: CanonicalCIOCycle,
        screening_store: SQLiteFullUniverseScreeningStore,
        context_provider: ProductionCanonicalCIOContextProvider,
    ) -> None:
        if not isinstance(cycle, CanonicalCIOCycle):
            raise TypeError("cycle must be CanonicalCIOCycle")
        if not isinstance(screening_store, SQLiteFullUniverseScreeningStore):
            raise TypeError(
                "screening_store must be SQLiteFullUniverseScreeningStore"
            )
        if not isinstance(context_provider, ProductionCanonicalCIOContextProvider):
            raise TypeError(
                "context_provider must implement ProductionCanonicalCIOContextProvider"
            )
        _required_text(context_provider.name, field_name="context_provider.name")
        self.cycle = cycle
        self.screening_store = screening_store
        self.context_provider = context_provider

    def run(self, *, as_of: datetime) -> CanonicalCIOCycleResult:
        decision_time = _aware(as_of, field_name="as_of")
        if not self.screening_store.verify_integrity():
            raise RuntimeError("complete-universe screening integrity is unavailable")
        context = self.context_provider.load_context(as_of=decision_time)
        if not isinstance(context, ProductionCanonicalCIOContext):
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
                "canonical CIO cycle requires a persisted complete-universe publication"
            )
        if publication.screened_instrument_count != publication.eligible_instrument_count:
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
        return self.cycle.run(
            identifier=context.identifier,
            candidates=candidates,
            opportunity_context=context.opportunity_context,
            specialist_contexts=context.specialist_contexts,
            portfolio=context.portfolio,
            code_version=context.code_version,
        )


__all__ = [
    "ProductionCanonicalCIOContext",
    "ProductionCanonicalCIOContextProvider",
    "ProductionCanonicalCIOExecutor",
]
