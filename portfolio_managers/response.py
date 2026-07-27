"""Portfolio manager response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from intelligence.metadata import DocumentMetadata


class MandateID(str, Enum):
    """The sole investment mandate: maximize long-term compounded returns.

    Liquidity, concentration, leverage, turnover, and prohibited-exposure
    controls are operational constraint profiles, not competing objectives.
    """

    COMPOUNDING = "compounding"


class TradeAction(str, Enum):
    """Supported paper-trade recommendation actions."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class ProposedTrade:
    """Trade proposed by a portfolio manager."""

    symbol: str
    action: TradeAction
    quantity: float | None = None
    target_weight: float | None = None
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")

        if self.quantity is not None and self.quantity < 0:
            raise ValueError("quantity cannot be negative")

        if (
            self.target_weight is not None and not 0.0 <= self.target_weight <= 1.0
        ):
            raise ValueError("target_weight must be between 0.0 and 1.0")


@dataclass
class PortfolioManagerResponse:
    """Formal response under the compounding mandate to official CIO guidance."""

    mandate_id: MandateID
    guidance_id: str

    agreement_level: float
    conviction: float

    implementation_summary: str
    commentary: str
    expected_return: str
    expected_risk: str

    rationale: list[str] = field(default_factory=list)
    proposed_trades: list[ProposedTrade] = field(default_factory=list)
    mandate_constraints_considered: list[str] = field(default_factory=list)

    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)

    def __post_init__(self) -> None:
        if not self.guidance_id.strip():
            raise ValueError("guidance_id cannot be empty")

        if not 0.0 <= self.agreement_level <= 1.0:
            raise ValueError("agreement_level must be between 0.0 and 1.0")

        if not 0.0 <= self.conviction <= 1.0:
            raise ValueError("conviction must be between 0.0 and 1.0")
