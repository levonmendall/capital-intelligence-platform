
from __future__ import annotations
import math
import pandas as pd
import numpy as np

def clamp(x, lo=0, hi=100):
    return float(max(lo, min(hi, x)))

def enrich_market(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ["move_1d","momentum_3m","momentum_12m","breadth","flow","risk_score","volatility"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["trend_score"] = (
        0.25 * np.clip((out["momentum_3m"] + 5) / 15 * 100, 0, 100) +
        0.35 * np.clip((out["momentum_12m"] + 10) / 30 * 100, 0, 100) +
        0.20 * out["breadth"] +
        0.20 * out["flow"]
    )
    out["risk_adjusted_score"] = np.clip(
        0.65 * out["trend_score"] + 0.35 * out["risk_score"] - 0.30 * out["volatility"], 0, 100
    )
    out["rank"] = out["risk_adjusted_score"].rank(ascending=False, method="dense").astype(int)
    out["cio_view"] = pd.cut(
        out["risk_adjusted_score"],
        bins=[-1,49,64,77,101],
        labels=["Avoid adding","Watch","Maintain","Increase"]
    ).astype(str)
    out["trend"] = np.where(out["momentum_3m"] > 5, "Improving",
                    np.where(out["momentum_3m"] > 0, "Constructive", "Weakening"))
    return out.sort_values("rank")

def regime_engine(market: pd.DataFrame) -> dict:
    eq = market[market["level"].isin(["Sector","Industry","Benchmark"])]
    avg_mom = eq["momentum_3m"].mean()
    avg_breadth = eq["breadth"].mean()
    avg_flow = eq["flow"].mean()
    avg_risk = eq["risk_score"].mean()
    avg_vol = eq["volatility"].mean()

    growth = clamp(50 + avg_mom*4)
    liquidity = clamp(avg_flow)
    breadth = clamp(avg_breadth)
    credit = clamp(avg_risk)
    volatility_safety = clamp(100 - avg_vol*2.2)
    composite = np.mean([growth, liquidity, breadth, credit, volatility_safety])

    if composite >= 72 and breadth >= 68:
        regime, posture = "Risk-On Expansion", "Growth-oriented"
    elif composite >= 62:
        regime, posture = "Late-Cycle Risk-On", "Moderately invested"
    elif composite >= 52:
        regime, posture = "Mixed / Transition", "Balanced"
    elif composite >= 42:
        regime, posture = "Slowdown", "Defensive tilt"
    else:
        regime, posture = "Risk-Off Contraction", "Capital preservation"

    confidence = clamp(55 + abs(composite-50)*0.7)
    risk_score = clamp(100-composite)
    return {
        "regime": regime, "posture": posture, "confidence": round(confidence,1),
        "risk_score": round(risk_score,1), "composite": round(composite,1),
        "components": {
            "Growth": round(growth,1), "Liquidity": round(liquidity,1),
            "Breadth": round(breadth,1), "Credit": round(credit,1),
            "Volatility safety": round(volatility_safety,1)
        }
    }

def specialist_committee(market: pd.DataFrame, regime: dict) -> pd.DataFrame:
    eq = market[market["level"].isin(["Sector","Industry","Benchmark"])]
    scores = {
        "Macro": regime["components"]["Growth"],
        "Trend": clamp(50 + eq["momentum_3m"].mean()*5),
        "Breadth": clamp(eq["breadth"].mean()),
        "Credit & Risk": clamp(eq["risk_score"].mean()),
        "Capital Flow": clamp(eq["flow"].mean()),
        "Portfolio": 62.0,
    }
    rows = []
    for name, score in scores.items():
        view = "Bullish" if score >= 70 else "Constructive" if score >= 58 else "Neutral" if score >= 45 else "Cautious"
        rows.append([name, round(score,1), view])
    return pd.DataFrame(rows, columns=["specialist","score","view"])

def portfolio_analysis(holdings: pd.DataFrame, market: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    h = holdings.copy()
    for c in ["market_value","cost_basis","max_weight"]:
        h[c] = pd.to_numeric(h[c], errors="coerce").fillna(0)
    total = h["market_value"].sum()
    h["weight"] = np.where(total > 0, h["market_value"]/total, 0)
    h["gain_loss"] = h["market_value"] - h["cost_basis"]
    h["gain_loss_pct"] = np.where(h["cost_basis"] > 0, h["gain_loss"]/h["cost_basis"], 0)
    m = market[["ticker","risk_adjusted_score","cio_view","volatility","level"]].copy()
    h = h.merge(m, how="left", on="ticker")
    h["risk_adjusted_score"] = h["risk_adjusted_score"].fillna(50)
    h["volatility"] = h["volatility"].fillna(5 if (h["ticker"]=="CASH").any() else 15)
    h["target_weight"] = h["weight"]

    # Rule-based targets with explicit caps and CIO score
    raw = np.where(h["ticker"].eq("CASH"), 0.12,
          np.where(h["risk_adjusted_score"] >= 78, h["weight"]*1.15,
          np.where(h["risk_adjusted_score"] < 55, h["weight"]*0.72, h["weight"])))
    raw = np.minimum(raw, h["max_weight"].replace(0,1))
    if raw.sum() > 0:
        h["target_weight"] = raw/raw.sum()
    h["weight_change"] = h["target_weight"] - h["weight"]
    h["dollar_adjustment"] = h["weight_change"] * total
    h["suggested_action"] = np.where(h["weight_change"] > 0.02, "Increase",
                             np.where(h["weight_change"] < -0.02, "Reduce", "Maintain"))
    h["risk_contribution"] = h["weight"] * h["volatility"]
    concentration = float((h["weight"]**2).sum())
    diversification = max(0, min(100, (1-concentration)*125))
    max_holding = h.loc[h["weight"].idxmax(), "ticker"] if len(h) else "—"
    summary = {
        "total": total,
        "gain_loss": h["gain_loss"].sum(),
        "equity_weight": float(h.loc[h["level"].isin(["Sector","Industry","Benchmark"]),"weight"].sum()),
        "defensive_weight": float(h.loc[h["level"].isin(["Asset Class"]),"weight"].sum()),
        "cash_weight": float(h.loc[h["ticker"].eq("CASH"),"weight"].sum()),
        "diversification": round(diversification,1),
        "concentration": round(concentration*100,1),
        "largest_holding": max_holding,
    }
    return h, summary

def build_decision(market: pd.DataFrame, regime: dict, specialists: pd.DataFrame, portfolio_summary: dict):
    top = market.iloc[0]
    weak = market.sort_values("risk_adjusted_score").iloc[0]
    concentrated = portfolio_summary["concentration"] > 24
    brief = (
        f"The environment is classified as {regime['regime']} with a {regime['posture'].lower()} posture. "
        f"Leadership favors {top['group']}, while {weak['group']} has the weakest risk-adjusted profile. "
        + ("Portfolio concentration is elevated and deserves attention." if concentrated else
           "Portfolio concentration is currently manageable.")
    )
    return {
        "regime": regime["regime"],
        "posture": regime["posture"],
        "confidence": regime["confidence"],
        "risk_score": regime["risk_score"],
        "brief": brief,
        "increase": str(top["group"]),
        "maintain": "Broad U.S. equities",
        "reduce": str(weak["group"]),
        "specialist_agreement": round((specialists["score"] >= 58).mean()*100,1)
    }

def stress_scenarios(portfolio: pd.DataFrame) -> pd.DataFrame:
    total = portfolio["market_value"].sum()
    eq_weight = portfolio.loc[portfolio["level"].isin(["Sector","Industry","Benchmark"]),"weight"].sum()
    tech_weight = portfolio.loc[portfolio["ticker"].isin(["SMH","SOXX","XLK"]),"weight"].sum()
    bond_weight = portfolio.loc[portfolio["ticker"].isin(["TLT","SHY"]),"weight"].sum()
    gold_weight = portfolio.loc[portfolio["ticker"].eq("GLD"),"weight"].sum()
    scenarios = [
        ("Equities -10%", -0.10*eq_weight),
        ("Technology -20%", -0.20*tech_weight),
        ("Rates +1%", -0.06*bond_weight),
        ("Credit spreads widen", -0.055*eq_weight),
        ("Dollar surge", -0.025*eq_weight + 0.015*gold_weight),
        ("Oil shock", -0.04*eq_weight),
        ("Recession estimate", -0.18*eq_weight + 0.03*bond_weight + 0.025*gold_weight),
    ]
    return pd.DataFrame([
        [name, impact, impact*total] for name, impact in scenarios
    ], columns=["scenario","estimated_return","estimated_dollar_impact"])
