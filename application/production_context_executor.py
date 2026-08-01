"""Runtime executor binding qualification to certified authority and evidence."""

from __future__ import annotations

import threading
from datetime import datetime
from types import SimpleNamespace

from application import production_context_contract as contract
from cio import CandidateAssetClass
from operations.free_paper_pilot import load_free_paper_pilot_universe
from screening import candidate_from_payload


_AUTHORITY_BINDING_LOCK = threading.RLock()
_EQUITY_CLASSES = frozenset(
    {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
    }
)


class _CachedContextProvider:
    """Return one already-loaded immutable context to the parent executor."""

    def __init__(self, delegate, context, *, as_of: datetime) -> None:
        self._delegate = delegate
        self._context = context
        self._as_of = as_of

    @property
    def code_version(self):
        return getattr(self._delegate, "code_version", None)

    def load_context(self, *, as_of: datetime):
        if as_of != self._as_of:
            raise ValueError("cached production context requested for another timestamp")
        return self._context


def _publication_candidates(executor, *, context):
    publication = executor.screening_store.publication(
        context.screening_cycle_identifier
    )
    if publication is None:
        raise RuntimeError(
            "canonical CIO cycle requires a persisted complete-universe publication"
        )
    return tuple(
        candidate_from_payload(payload)
        for payload in publication.candidate_payloads
    )


def _validate_specialist_valuation_coverage(executor, *, context) -> None:
    """Fail closed when certified valuation evidence is missing in production."""

    candidate_map = {
        candidate.identifier: candidate
        for candidate in _publication_candidates(executor, context=context)
    }
    for specialist_context in context.specialist_contexts:
        candidate = candidate_map.get(specialist_context.candidate_identifier)
        if candidate is None:
            raise RuntimeError(
                "production specialist context references an unknown candidate"
            )
        asset_class = candidate.instrument.asset_class
        if asset_class in _EQUITY_CLASSES:
            if specialist_context.company is None:
                raise RuntimeError(
                    f"equity candidate {candidate.identifier} is missing certified "
                    "company and valuation analysis"
                )
        elif specialist_context.asset_valuation is None:
            raise RuntimeError(
                f"non-equity candidate {candidate.identifier} is missing certified "
                "asset-specific valuation analysis"
            )


def _candidate_authority_universe(executor, *, context):
    """Build the exact authority view consumed by runtime requalification.

    The completed screening publication already contains immutable candidate
    instrument identities. Requalification therefore derives its allowlist from
    those exact records instead of requiring a second filesystem artifact. When
    the publication contains no candidates, the authority cannot affect the empty
    queue, so the configured static universe is used only as a non-operative
    structural placeholder.
    """

    candidates = _publication_candidates(executor, context=context)
    if not candidates:
        return load_free_paper_pilot_universe()
    instruments = tuple(
        SimpleNamespace(
            instrument_identifier=candidate.instrument.instrument_id,
            symbol=candidate.instrument.symbol,
            execution_asset_class=candidate.instrument.asset_class,
            economic_exposure=(
                candidate.instrument.economic_exposure_class.value
                if candidate.instrument.economic_exposure_class is not None
                else candidate.instrument.asset_class.value
            ),
            venue=candidate.instrument.venue,
            country_code=candidate.instrument.country_code,
            instrument_type=candidate.instrument.instrument_type,
        )
        for candidate in candidates
    )
    return SimpleNamespace(
        identifier=context.eligible_universe_publication_identifier,
        instruments=instruments,
    )


class ProductionCanonicalCIOExecutor(contract.ProductionCanonicalCIOExecutor):
    """Execute only with exact authority and role-complete certified evidence."""

    def run(self, *, as_of: datetime):
        # Load the immutable context exactly once. The parent executor receives a
        # timestamp-bound cache and still performs all publication, snapshot,
        # ranking, manifest, portfolio, and journal integrity checks.
        original_provider = self.context_provider
        context = original_provider.load_context(as_of=as_of)
        _validate_specialist_valuation_coverage(self, context=context)
        authority_universe = _candidate_authority_universe(self, context=context)
        publication_identifier = authority_universe.identifier

        def load_exact_authority(requested_identifier: str):
            if str(requested_identifier).strip() != publication_identifier:
                raise ValueError(
                    "runtime authority request does not match the certified publication"
                )
            return authority_universe

        # The parent contract owns every other integrity check. The lock keeps
        # both narrow dependency injections process-local and deterministic.
        with _AUTHORITY_BINDING_LOCK:
            original_loader = contract.load_active_paper_universe_for_publication
            contract.load_active_paper_universe_for_publication = load_exact_authority
            self.context_provider = _CachedContextProvider(
                original_provider,
                context,
                as_of=as_of,
            )
            try:
                return super().run(as_of=as_of)
            finally:
                self.context_provider = original_provider
                contract.load_active_paper_universe_for_publication = original_loader


__all__ = ["ProductionCanonicalCIOExecutor"]
