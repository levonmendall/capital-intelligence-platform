"""Single-load facade for the capability-certified production CIO executor.

The implementation preloads the governed context before binding exact market
participation authority. Legacy and rehearsal contexts then delegate to the base
executor. This facade memoizes that load for the duration of one run so every cycle
observes one point-in-time context read, regardless of which execution path applies.
It also preserves the module-level monkeypatch boundary used by authority tests and
operational adapters.

Production decisions additionally bind the active-universe loader and market authority
to the exact CIO timestamp and the capability database adjacent to canonical portfolio
state.  This makes the Universal Capability Graph certification a real ownership gate
without changing historical/rehearsal behavior.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from application import production_context_executor_impl as _implementation
from application.decision_intelligence_v3_runtime import (
    append_post_cycle_decision_intelligence,
)
from application.marginal_targeting_runtime import (
    install_construction_backed_marginal_targeting,
)
from governance.market_participation import (
    CanonicalMarketParticipationAuthority as _CanonicalMarketParticipationAuthority,
)
from operations.active_paper_universe import (
    load_active_paper_universe_for_publication as _load_active_paper_universe,
)
from operations.certification_cycle_lineage import certify_completed_cio_cycle

_LOGGER = logging.getLogger("capital_intelligence.decision_intelligence_v3")
_ORIGINAL_CANDIDATE_AUTHORITY_UNIVERSE = (
    _implementation._candidate_authority_universe
)
_IMPLEMENTATION_NAMES = tuple(vars(_implementation))
_WRAPPED_NAMES = frozenset(
    {"ProductionCanonicalCIOExecutor", "_candidate_authority_universe"}
)
_RUNTIME_AUTHORITY = threading.local()


for _name, _value in vars(_implementation).items():
    if _name.startswith("__") or _name in _WRAPPED_NAMES:
        continue
    globals()[_name] = _value


# Production ranking and portfolio-specialist previews use the same canonical
# construction engine instead of a maximum-position proxy. The binding is idempotent
# and leaves direct imports of the historical cycle untouched until the production
# executor is composed.
install_construction_backed_marginal_targeting()


def _runtime_capability_database(provider) -> Path | None:
    visited: set[int] = set()
    current = provider
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        store = getattr(current, "portfolio_store", None)
        path = getattr(store, "path", None)
        if path is not None:
            return Path(path).expanduser().with_name("instrument-paper-eligibility.db")
        current = getattr(current, "_delegate", None) or getattr(
            current, "_stored_provider", None
        )
    return None


def _runtime_active_universe_loader(
    publication_identifier: str,
    *,
    path=None,
    evaluated_at=None,
):
    timestamp = evaluated_at or getattr(_RUNTIME_AUTHORITY, "as_of", None)
    return _load_active_paper_universe(
        publication_identifier,
        path=path,
        evaluated_at=timestamp,
    )


class _RuntimeMarketParticipationAuthority:
    @classmethod
    def load(cls, *args, **kwargs):
        if kwargs.get("capability_database_path") is None:
            database_path = getattr(_RUNTIME_AUTHORITY, "capability_database", None)
            if database_path is not None:
                kwargs["capability_database_path"] = database_path
        return _CanonicalMarketParticipationAuthority.load(*args, **kwargs)


def _synchronize_runtime_bindings() -> None:
    """Propagate facade monkeypatches into implementation function globals."""

    for name in _IMPLEMENTATION_NAMES:
        if name.startswith("__") or name in _WRAPPED_NAMES:
            continue
        if name in globals():
            _implementation.__dict__[name] = globals()[name]
    _implementation.load_active_paper_universe_for_publication = (
        _runtime_active_universe_loader
    )
    _implementation.CanonicalMarketParticipationAuthority = (
        _RuntimeMarketParticipationAuthority
    )


class _SingleLoadContextProvider:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self._cached_as_of: datetime | None = None
        self._cached_context = None

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def load_context(self, *, as_of: datetime):
        if self._cached_context is None:
            self._cached_context = self._delegate.load_context(as_of=as_of)
            self._cached_as_of = as_of
        elif as_of != self._cached_as_of:
            raise ValueError("context provider requested for another timestamp")
        return self._cached_context


def _candidate_authority_universe(executor, *, context):
    _synchronize_runtime_bindings()
    return _ORIGINAL_CANDIDATE_AUTHORITY_UNIVERSE(
        executor,
        context=context,
    )


class ProductionCanonicalCIOExecutor(
    _implementation.ProductionCanonicalCIOExecutor
):
    """Execute one cycle from exactly one provider context read."""

    def run(self, *, as_of: datetime):
        original_provider = self.context_provider
        cached_provider = _SingleLoadContextProvider(original_provider)
        self.context_provider = cached_provider
        _RUNTIME_AUTHORITY.as_of = as_of
        _RUNTIME_AUTHORITY.capability_database = _runtime_capability_database(
            original_provider
        )
        _synchronize_runtime_bindings()
        try:
            result = super().run(as_of=as_of)

            # Operational certification is derived from the canonical artifacts after
            # authority has already acted. It cannot alter the CIO decision, but a
            # production lineage failure must remain visible/fail-closed to operational
            # certification instead of being silently inferred later.
            certify_completed_cio_cycle(result)

            # Decision Intelligence v3 is downstream and read-only. A persistence
            # failure may reduce explainability/measurement coverage, but it must not
            # invalidate or change a CIO decision already produced by the canonical
            # authority path.
            try:
                append_post_cycle_decision_intelligence(
                    result=result,
                    context=cached_provider._cached_context,
                )
            except Exception:
                _LOGGER.exception(
                    "post-cycle decision-intelligence persistence failed for %s",
                    getattr(result, "identifier", "unknown"),
                )
            return result
        finally:
            self.context_provider = original_provider
            _RUNTIME_AUTHORITY.as_of = None
            _RUNTIME_AUTHORITY.capability_database = None


__all__ = ["ProductionCanonicalCIOExecutor"]
