"""Retired model-portfolio compatibility helpers for offline research only.

Defensive, Balanced, and Growth allocations are not active portfolio authorities
and cannot produce a canonical CIO action or write canonical portfolio state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_FILE = ROOT / "config" / "legacy" / "model_portfolios.json"


@dataclass(frozen=True)
class TradeRecommendation:
    """A historical research recommendation, never an active product action."""

    action: str
    symbol: str
    target_weight: float
    rationale: str


def load_model_portfolios() -> dict:
    """Load retired model allocations for isolated offline comparison."""

    with MODEL_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def determine_model(regime: str) -> str:
    """Classify a historical model for offline legacy analysis."""

    normalized = regime.lower()
    if "recession" in normalized:
        return "Defensive"
    if "inflation" in normalized or "slowdown" in normalized:
        return "Balanced"
    return "Growth"


def build_trade_recommendations():
    """Reject attempts to use retired model portfolios as active authority."""

    raise RuntimeError(
        "retired model portfolios are offline research only; canonical CIO "
        "construction must allocate the COMPOUNDING portfolio"
    )
