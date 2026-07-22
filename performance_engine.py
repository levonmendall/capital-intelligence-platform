from __future__ import annotations
import math
from core.database import connection

def mandate_metrics(mandate_id: str) -> dict:
    with connection() as conn:
        rows = conn.execute(
            """SELECT valuation_date, nav FROM nav_history
               WHERE mandate_id=? ORDER BY valuation_date""",
            (mandate_id,),
        ).fetchall()
        trades = conn.execute(
            """SELECT COALESCE(SUM(total_fees),0) AS fees,
                      COALESCE(SUM(ABS(gross_value)),0) AS turnover_value
               FROM trades WHERE mandate_id=?""",
            (mandate_id,),
        ).fetchone()
        mandate = conn.execute(
            "SELECT starting_capital FROM mandates WHERE mandate_id=?",
            (mandate_id,),
        ).fetchone()

    navs = [float(r["nav"]) for r in rows]
    start = float(mandate["starting_capital"])
    end = navs[-1] if navs else start
    returns = [(navs[i] / navs[i-1] - 1) for i in range(1, len(navs)) if navs[i-1] > 0]
    volatility = 0.0
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((x - mean) ** 2 for x in returns) / (len(returns) - 1)
        volatility = math.sqrt(variance) * math.sqrt(252)

    peak = navs[0] if navs else start
    max_dd = 0.0
    for nav in navs:
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)

    return {
        "start_value": start,
        "current_value": end,
        "net_gain": end - start,
        "net_return": end / start - 1,
        "annualized_volatility": volatility,
        "max_drawdown": max_dd,
        "total_fees": float(trades["fees"]),
        "turnover_value": float(trades["turnover_value"]),
        "observations": len(navs),
    }
