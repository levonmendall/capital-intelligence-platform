"""Non-authoritative stretch-compounding diagnostics.

The governed portfolio objective remains maximizing long-term compounded returns
after costs.  This module supplies a 5% monthly *reference trajectory* for
performance review and investor education only.  It has no dependency on, and no
authority over, opportunity qualification, CIO ranking, portfolio construction,
sizing, or execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = "compounding-aspiration.v1"
MONTHLY_STRETCH_RATE = 0.05
MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class CompoundingAspiration:
    """A deliberately non-authoritative compounding reference."""

    schema_version: str = SCHEMA_VERSION
    label: str = "5% Monthly Compounding Aspiration"
    monthly_reference_rate: float = MONTHLY_STRETCH_RATE
    annualized_reference_rate: float = (1.0 + MONTHLY_STRETCH_RATE) ** MONTHS_PER_YEAR - 1.0
    reference_only: bool = True
    authoritative: bool = False
    affects_qualification: bool = False
    affects_ranking: bool = False
    affects_sizing: bool = False
    affects_construction: bool = False
    affects_execution: bool = False
    can_force_trade: bool = False
    can_override_cash: bool = False
    can_relax_risk: bool = False
    catch_up_risk_authorized: bool = False
    diagnostic_purpose: str = (
        "Use a demanding return trajectory to review opportunity capture, evidence quality, "
        "portfolio construction efficiency, and possible false conservatism without changing "
        "the governed investment process."
    )
    trailing_reference_response: str = (
        "Trailing the reference triggers process review, not a requirement to catch up, "
        "increase risk, lower thresholds, or manufacture a trade."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stretch_multiple(months: int) -> float:
    """Return the reference capital multiple after ``months`` months."""

    if isinstance(months, bool) or not isinstance(months, int):
        raise TypeError("months must be an integer")
    if months < 0:
        raise ValueError("months must be non-negative")
    return (1.0 + MONTHLY_STRETCH_RATE) ** months


def stretch_value(starting_capital: float, months: int) -> float:
    """Return the illustrative reference value for a starting capital amount."""

    if isinstance(starting_capital, bool):
        raise TypeError("starting_capital must be numeric")
    try:
        capital = float(starting_capital)
    except (TypeError, ValueError) as exc:
        raise TypeError("starting_capital must be numeric") from exc
    if capital < 0:
        raise ValueError("starting_capital must be non-negative")
    return capital * stretch_multiple(months)


def build_compounding_aspiration() -> CompoundingAspiration:
    """Return the canonical stretch-compounding diagnostic definition."""

    return CompoundingAspiration()


__all__ = [
    "SCHEMA_VERSION",
    "MONTHLY_STRETCH_RATE",
    "MONTHS_PER_YEAR",
    "CompoundingAspiration",
    "build_compounding_aspiration",
    "stretch_multiple",
    "stretch_value",
]
