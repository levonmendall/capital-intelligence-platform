from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from core.config_loader import mandates
from core.database import connection

@dataclass(frozen=True)
class CIOView:
    regime: str
    confidence: float
    risk_score: float
    growth_score: float
    inflation_score: float
    liquidity_score: float
    breadth_score: float

def infer_market_view(signals: dict[str, float] | None = None) -> CIOView:
    """
    Deterministic, explainable Sprint 1 CIO view.
    Inputs should be normalized 0..100. Missing inputs remain neutral.
    """
    s = signals or {}
    growth = float(s.get("growth", 50))
    inflation = float(s.get("inflation", 50))
    liquidity = float(s.get("liquidity", 50))
    breadth = float(s.get("breadth", 50))
    volatility = float(s.get("volatility", 50))

    risk_score = (
        0.30 * growth + 0.25 * liquidity + 0.25 * breadth + 0.20 * (100 - volatility)
    )

    if growth >= 55 and inflation <= 60 and risk_score >= 60:
        regime = "Expansion"
    elif growth < 45 and inflation >= 55:
        regime = "Stagflation Risk"
    elif growth < 45:
        regime = "Slowdown"
    elif inflation > 65:
        regime = "Inflation Pressure"
    else:
        regime = "Transition"

    dispersion = max(s.values()) - min(s.values()) if s else 0
    confidence = max(0.50, min(0.95, 0.78 - dispersion / 250))
    return CIOView(regime, confidence, risk_score, growth, inflation, liquidity, breadth)

def target_allocations(view: CIOView) -> dict[str, dict[str, float]]:
    risk_on = view.risk_score >= 60
    risk_off = view.risk_score < 45

    allocations = {
        "capital_preservation": {"SGOV": 0.55, "SHY": 0.20, "TIP": 0.10, "GLD": 0.05, "CASH": 0.10},
        "income_stability": {"SCHD": 0.25, "LQD": 0.25, "SHY": 0.20, "TIP": 0.10, "USMV": 0.10, "CASH": 0.10},
        "balanced_allocation": {"VTI": 0.35, "VEA": 0.12, "VWO": 0.05, "IEF": 0.20, "LQD": 0.10, "GLD": 0.08, "CASH": 0.10},
        "growth_opportunities": {"SPY": 0.30, "QQQ": 0.25, "IWM": 0.10, "QUAL": 0.15, "XLK": 0.10, "CASH": 0.10},
        "tactical_rotation": {"SPY": 0.25, "XLI": 0.20, "XLV": 0.15, "GLD": 0.10, "IEF": 0.10, "CASH": 0.20},
        "opportunistic_value": {"IWD": 0.35, "QUAL": 0.20, "SCHD": 0.15, "XLF": 0.10, "XLE": 0.08, "CASH": 0.12},
        "global_opportunities": {"SPY": 0.25, "VEA": 0.20, "VWO": 0.15, "EWJ": 0.10, "INDA": 0.10, "GLD": 0.08, "CASH": 0.12},
        "innovation_disruption": {"QQQ": 0.25, "SMH": 0.20, "CIBR": 0.15, "BOTZ": 0.12, "XBI": 0.10, "ARKK": 0.08, "CASH": 0.10},
    }

    if risk_on:
        allocations["growth_opportunities"]["CASH"] = 0.05
        allocations["growth_opportunities"]["SPY"] += 0.05
        allocations["tactical_rotation"] = {"SPY": 0.25, "QQQ": 0.20, "XLI": 0.20, "IWM": 0.15, "GLD": 0.05, "CASH": 0.15}
        allocations["innovation_disruption"]["CASH"] = 0.05
        allocations["innovation_disruption"]["SMH"] += 0.05
    elif risk_off:
        allocations["capital_preservation"] = {"SGOV": 0.60, "SHY": 0.20, "TIP": 0.08, "GLD": 0.07, "CASH": 0.05}
        allocations["balanced_allocation"] = {"VTI": 0.20, "USMV": 0.15, "IEF": 0.25, "SHY": 0.15, "GLD": 0.10, "CASH": 0.15}
        allocations["growth_opportunities"] = {"SPY": 0.25, "QUAL": 0.20, "USMV": 0.15, "SHY": 0.15, "GLD": 0.05, "CASH": 0.20}
        allocations["tactical_rotation"] = {"SGOV": 0.30, "IEF": 0.20, "GLD": 0.15, "XLV": 0.10, "XLP": 0.10, "CASH": 0.15}
        allocations["innovation_disruption"]["CASH"] = 0.25
        allocations["innovation_disruption"]["QQQ"] = 0.20

    for mandate_id, weights in allocations.items():
        total = sum(weights.values())
        allocations[mandate_id] = {k: round(v / total, 6) for k, v in weights.items()}
    return allocations

def create_decision(signals: dict[str, float] | None = None, notes: str = "") -> int:
    view = infer_market_view(signals)
    allocations = target_allocations(view)
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO cio_decisions
            (timestamp, regime, confidence, market_view_json, target_allocations_json, approved, notes)
            VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (
                now, view.regime, view.confidence,
                json.dumps(view.__dict__, sort_keys=True),
                json.dumps(allocations, sort_keys=True),
                notes,
            ),
        )
        return int(cur.lastrowid)
