"""Single-load facade for the capability-certified production CIO executor.

The implementation preloads the governed context before binding exact market
participation authority. The facade memoizes that load for one run. A completed canonical
result advances durable committee, CIO, and construction certification before the worker
can declare the operational cycle complete; downstream decision-intelligence remains
read-only and non-authoritative.
"""
from __future__ import annotations
import logging
from datetime import datetime
from application import production_context_executor_impl as _implementation
from application.decision_intelligence_v3_runtime import append_post_cycle_decision_intelligence
from application.marginal_targeting_runtime import install_construction_backed_marginal_targeting
from operations.certification_cycle_lineage import certify_completed_cio_cycle

_LOGGER=logging.getLogger("capital_intelligence.decision_intelligence_v3")
_ORIGINAL_CANDIDATE_AUTHORITY_UNIVERSE=_implementation._candidate_authority_universe
_IMPLEMENTATION_NAMES=tuple(vars(_implementation)); _WRAPPED_NAMES=frozenset({"ProductionCanonicalCIOExecutor","_candidate_authority_universe"})
for _name,_value in vars(_implementation).items():
    if _name.startswith("__") or _name in _WRAPPED_NAMES: continue
    globals()[_name]=_value
install_construction_backed_marginal_targeting()
def _synchronize_runtime_bindings()->None:
    for name in _IMPLEMENTATION_NAMES:
        if name.startswith("__") or name in _WRAPPED_NAMES: continue
        if name in globals(): _implementation.__dict__[name]=globals()[name]
class _SingleLoadContextProvider:
    def __init__(self,delegate)->None: self._delegate=delegate; self._cached_as_of:datetime|None=None; self._cached_context=None
    def __getattr__(self,name:str): return getattr(self._delegate,name)
    def load_context(self,*,as_of:datetime):
        if self._cached_context is None: self._cached_context=self._delegate.load_context(as_of=as_of); self._cached_as_of=as_of
        elif as_of!=self._cached_as_of: raise ValueError("context provider requested for another timestamp")
        return self._cached_context
def _candidate_authority_universe(executor,*,context):
    _synchronize_runtime_bindings(); return _ORIGINAL_CANDIDATE_AUTHORITY_UNIVERSE(executor,context=context)
class ProductionCanonicalCIOExecutor(_implementation.ProductionCanonicalCIOExecutor):
    def run(self,*,as_of:datetime):
        _synchronize_runtime_bindings(); original_provider=self.context_provider; cached_provider=_SingleLoadContextProvider(original_provider); self.context_provider=cached_provider
        try:
            result=super().run(as_of=as_of)
            certify_completed_cio_cycle(result)
            try: append_post_cycle_decision_intelligence(result=result,context=cached_provider._cached_context)
            except Exception: _LOGGER.exception("post-cycle decision-intelligence persistence failed for %s",getattr(result,"identifier","unknown"))
            return result
        finally: self.context_provider=original_provider
__all__=["ProductionCanonicalCIOExecutor"]
