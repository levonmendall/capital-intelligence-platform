from __future__ import annotations
from core.config_loader import settings
from core.portfolio_engine import portfolio_snapshot

def build_trade_plan(
    mandate_id: str,
    target_weights: dict[str, float],
    prices: dict[str, float],
) -> list[dict]:
    """
    Produces a paper trade proposal. It does not execute anything.
    Sells are listed before buys. CASH is the residual and is never traded.
    """
    snapshot = portfolio_snapshot(mandate_id)
    nav = snapshot.nav
    if nav <= 0:
        return []

    current_values = {
        p["symbol"]: float(p["quantity"]) * float(p["last_price"])
        for p in snapshot.positions
    }
    symbols = set(current_values) | {s for s in target_weights if s != "CASH"}
    drift_limit = float(settings()["rebalance"]["minimum_drift"])
    min_trade = float(settings()["execution"]["minimum_trade_value"])
    plan = []

    for symbol in symbols:
        price = float(prices.get(symbol, 0))
        if price <= 0:
            continue
        current = current_values.get(symbol, 0.0)
        target = nav * float(target_weights.get(symbol, 0.0))
        delta = target - current
        drift = abs(delta) / nav
        if drift < drift_limit or abs(delta) < min_trade:
            continue
        plan.append({
            "symbol": symbol,
            "side": "BUY" if delta > 0 else "SELL",
            "target_weight": float(target_weights.get(symbol, 0)),
            "current_value": current,
            "target_value": target,
            "trade_value": abs(delta),
            "quantity": abs(delta) / price,
            "market_price": price,
        })
    return sorted(plan, key=lambda x: (x["side"] == "BUY", -x["trade_value"]))
