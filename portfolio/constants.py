"""Binding constants for the sole active Capital Intelligence portfolio."""

from __future__ import annotations

CANONICAL_PORTFOLIO_CODE = "COMPOUNDING"
CANONICAL_PORTFOLIO_NAME = "Capital Intelligence Portfolio"
CANONICAL_CONSTRAINT_PROFILE = "Operational constraints only"
CANONICAL_BASE_CURRENCY = "USD"
INITIAL_PAPER_CAPITAL = 250_000.0

PORTFOLIO_OBJECTIVE = (
    "Analyze all supported liquid public markets and allocate capital to the "
    "strongest evidence-supported expected net returns, after implementation "
    "costs and within approved portfolio and operating constraints."
)

__all__ = [
    "CANONICAL_BASE_CURRENCY",
    "CANONICAL_CONSTRAINT_PROFILE",
    "CANONICAL_PORTFOLIO_CODE",
    "CANONICAL_PORTFOLIO_NAME",
    "INITIAL_PAPER_CAPITAL",
    "PORTFOLIO_OBJECTIVE",
]
