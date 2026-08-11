"""Single-pass Massive option fallback hydration for governed discovery.

The base Massive adapter deliberately keeps provider mechanics isolated from discovery
policy.  This wrapper changes no contract eligibility, moneyness, pricing, evidence,
CIO, construction, or execution rule.  It only makes the first fallback contract
selection request enough daily-bar history to satisfy the canonical downstream option
feature window, so the existing process-wide Massive cache can be reused by provider
preselection and deep market probing without repeating the same option-bar requests.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from typing import Mapping, Sequence

from providers.massive_options import (
    MassiveOptionBar,
    MassiveOptionSelection,
    MassiveOptionsProvider,
)


_DEFAULT_SELECTION_HISTORY_DAYS = 365
_SELECTION_HISTORY_DAYS: ContextVar[int | None] = ContextVar(
    "massive_option_selection_history_days",
    default=None,
)


class SinglePassMassiveOptionsProvider(MassiveOptionsProvider):
    """Hydrate reusable option history during contract selection without extra calls."""

    def __init__(
        self,
        *args,
        selection_history_days: int = _DEFAULT_SELECTION_HISTORY_DAYS,
        **kwargs,
    ) -> None:
        if (
            isinstance(selection_history_days, bool)
            or not isinstance(selection_history_days, int)
            or selection_history_days < 1
            or selection_history_days > 730
        ):
            raise ValueError("selection_history_days must be between 1 and 730")
        super().__init__(*args, **kwargs)
        self._selection_history_days = selection_history_days

    def select_contracts(self, *args, **kwargs) -> tuple[MassiveOptionSelection, ...]:
        token = _SELECTION_HISTORY_DAYS.set(self._selection_history_days)
        try:
            return super().select_contracts(*args, **kwargs)
        finally:
            _SELECTION_HISTORY_DAYS.reset(token)

    def daily_bars(
        self,
        raw_symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> Mapping[str, tuple[MassiveOptionBar, ...]]:
        selection_history_days = _SELECTION_HISTORY_DAYS.get()
        effective_history_days = (
            history_days
            if selection_history_days is None
            else max(history_days, selection_history_days)
        )
        return super().daily_bars(
            raw_symbols,
            as_of=as_of,
            history_days=effective_history_days,
        )


__all__ = ["SinglePassMassiveOptionsProvider"]
