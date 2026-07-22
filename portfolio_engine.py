from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timezone
from core.database import connection

@dataclass(frozen=True)
class PortfolioSnapshot:
    mandate_id: str
    cash: float
    securities_value: float
    nav: float
    positions: list[dict]

def cash_balance(conn, mandate_id: str) -> float:
    row = conn.execute(
        """SELECT balance_after FROM cash_ledger
           WHERE mandate_id=? ORDER BY id DESC LIMIT 1""",
        (mandate_id,),
    ).fetchone()
    return float(row["balance_after"]) if row else 0.0

def portfolio_snapshot(mandate_id: str) -> PortfolioSnapshot:
    with connection() as conn:
        cash = cash_balance(conn, mandate_id)
        rows = conn.execute(
            """SELECT symbol, quantity, average_cost, last_price
               FROM positions WHERE mandate_id=? AND quantity > 0""",
            (mandate_id,),
        ).fetchall()
        positions = [dict(row) for row in rows]
        securities = sum(float(r["quantity"]) * float(r["last_price"]) for r in rows)
        return PortfolioSnapshot(
            mandate_id=mandate_id,
            cash=cash,
            securities_value=securities,
            nav=cash + securities,
            positions=positions,
        )

def all_portfolios() -> list[dict]:
    with connection() as conn:
        mandates = conn.execute(
            "SELECT * FROM mandates ORDER BY display_name"
        ).fetchall()
    result = []
    for m in mandates:
        snap = portfolio_snapshot(m["mandate_id"])
        result.append({
            **dict(m),
            "cash": snap.cash,
            "securities_value": snap.securities_value,
            "nav": snap.nav,
            "gain_loss": snap.nav - float(m["starting_capital"]),
            "return_pct": snap.nav / float(m["starting_capital"]) - 1.0,
            "positions_count": len(snap.positions),
        })
    return result

def update_prices(prices: dict[str, float]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        for symbol, price in prices.items():
            if price <= 0:
                continue
            conn.execute(
                "UPDATE positions SET last_price=?, updated_at=? WHERE symbol=?",
                (float(price), now, symbol.upper()),
            )

def record_daily_nav(valuation_date: str | None = None) -> None:
    day = valuation_date or date.today().isoformat()
    for portfolio in all_portfolios():
        with connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO nav_history
                (mandate_id, valuation_date, cash, securities_value, accrued_expenses, nav, benchmark_value)
                VALUES (?, ?, ?, ?, 0, ?, NULL)""",
                (
                    portfolio["mandate_id"], day, portfolio["cash"],
                    portfolio["securities_value"], portfolio["nav"]
                ),
            )
