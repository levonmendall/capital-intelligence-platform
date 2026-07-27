"""Production executor for the canonical CIO decision cycle.

The executor binds the scheduled decision process to one complete-universe
screening publication. External adapters may provide specialist and portfolio
context, but they cannot replace the candidate set or bypass immutable
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


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(
            f"{field_name} must contain at least {minimum} item(s)"
        )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _versions(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        (
            _required_text(name, field_name=f"{field_name} name"),
            _required_text(version, field_name=f"{field_name} version"),
        )
        for name, version in value
    )
    names = tuple(name for name, _ in normalized)
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class ProductionContextManifest:
    """Immutable lineage proving how one production context was assembled."""

    identifier: str
    screening_publication_identifier: str
    portfolio_snapshot_identifier: str
    context_evidence_identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    candidate_identifiers: tuple[str, ...]
    candidate_context_identifiers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    model_versions: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "screening_publication_identifier",
            "portfolio_snapshot_identifier",
            "context_evidence_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        _aware(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        for field_name, minimum in (
            ("candidate_identifiers", 0),
            ("candidate_context_identifiers", 0),
            ("evidence_identifiers", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        object.__setattr__(
            self,
            "source_versions",
            _versions(self.source_versions, field_name="source_versions"),
        )
        object.__setattr__(
            self,
            "model_versions",
            _versions(self.model_versions, field_name="model_versions"),
        )
        if len(self.candidate_context_identifiers) != len(
            self.candidate_identifiers
        ):
            raise ValueError(
                "each qualified candidate must have one context identifier"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "screening_publication_identifier": (
                self.screening_publication_identifier
            ),
            "portfolio_snapshot_identifier": self.portfolio_snapshot_identifier,
            "context_evidence_identifier": self.context_evidence_identifier,
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "candidate_identifiers": list(self.candidate_identifiers),
            "candidate_context_identifiers": list(
                self.candidate_context_identifiers
            ),
            "evidence_identifiers": list(self.evidence_identifiers),
            "source_versions": [list(item) for item in self.source_versions],
            "model_versions": [list(item) for item in self.model_versions],
        }


@dataclass(frozen=True, slots=True)
class ProductionCanonicalCIOContext:
    """Non-candidate inputs required to execute one canonical CIO cycle."""

    identifier: str
    screening_cycle_identifier: str
    opportunity_context: OpportunitySetContext
    specialist_contexts: tuple[CandidateCycleContext, ...]
    portfolio: CyclePortfolioState
    code_version: str = "unknown"
    manifest: ProductionContextManifest | None = None

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
        if self.manifest is not None:
            if not isinstance(self.manifest, ProductionContextManifest):
                raise TypeError(
                    "manifest must be ProductionContextManifest or None"
                )
            if self.manifest.as_of != self.portfolio.as_of:
                raise ValueError(
                    "production context manifest must share the decision timestamp"
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
        ranked = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("ranked", ())
        )
        qualified_identifiers = tuple(
            _required_text(
                item.get("candidate_identifier"),
                field_name="qualified candidate identifier",
            )
            for item in ranked
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
    "ProductionContextManifest",
]
