"""Single-load facade for the capability-certified production CIO executor.

The implementation preloads the governed context before binding exact market
participation authority. Legacy and rehearsal contexts then delegate to the base
executor. This facade memoizes that load for the duration of one run so every cycle
observes one point-in-time context read, regardless of which execution path applies.
It also preserves the module-level monkeypatch boundary used by authority tests and
operational adapters.
"""

from __future__ import annotations

from datetime import datetime

from application import production_context_executor_impl as _implementation

_ORIGINAL_CANDIDATE_AUTHORITY_UNIVERSE = (
    _implementation._candidate_authority_universe
)
_IMPLEMENTATION_NAMES = tuple(vars(_implementation))
_WRAPPED_NAMES = frozenset(
    {"ProductionCanonicalCIOExecutor", "_candidate_authority_universe"}
)


for _name, _value in vars(_implementation).items():
    if _name.startswith("__") or _name in _WRAPPED_NAMES:
        continue
    globals()[_name] = _value


def _synchronize_runtime_bindings() -> None:
    """Propagate facade monkeypatches into implementation function globals."""

    for name in _IMPLEMENTATION_NAMES:
        if name.startswith("__") or name in _WRAPPED_NAMES:
            continue
        if name in globals():
            _implementation.__dict__[name] = globals()[name]


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
        _synchronize_runtime_bindings()
        original_provider = self.context_provider
        self.context_provider = _SingleLoadContextProvider(original_provider)
        try:
            return super().run(as_of=as_of)
        finally:
            self.context_provider = original_provider


__all__ = ["ProductionCanonicalCIOExecutor"]
