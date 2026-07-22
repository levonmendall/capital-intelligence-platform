from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from core.config_loader import settings
from core.database import connection
from core.portfolio_engine import cash_balance

@dataclass(frozen=True)
class ExecutionResult:
    trade_id: int
    mandate_id: str
    symbol: str
    side: str
    quantity: float
    execution_price: float
    total_fees: float
    cash_after: float

class ExecutionError(ValueError):
    pass

def _costs(side: str, quantity: float, market_price: float) -> dict:
    cfg = settings()["execution"]
    gross = quantity * market_price
    spread = gross * float(cfg["spread_bps"]) / 10000
    slippage = gross * float(cfg["slippage_bps"]) / 10000
    commission = float(cfg["commission_per_trade"])
    regulatory = gross * float(cfg["sell_regulatory_fee_bps"]) / 10000 if side == "SELL" else 0.0
    execution_price = market_price * (
        1 + (float(cfg["spread_bps"]) + float(cfg["slippage_bps"])) / 10000
        if side == "BUY"
        else 1 - (float(cfg["spread_bps"]) + float(cfg["slippage_bps"])) / 10000
    )
    total_fees = spread + slippage + commission + regulatory
    return {
        "gross": gross,
        "spread": spread,
        "slippage": slippage,
        "commission": commission,
        "regulatory": regulatory,
        "execution_price": execution_price,
        "total_fees": total_fees,
    }

def execute_paper_trade(
    mandate_id: str,
    symbol: str,
    side: str,
    quantity: float,
    market_price: float,
    rationale: str = "",
    decision_id: int | None = None,
) -> ExecutionResult:
    if not settings()["paper_trading_only"]:
        raise ExecutionError("Live trading is disabled by design.")
    side = side.upper()
    symbol = symbol.upper().strip()
    if side not in {"BUY", "SELL"}:
        raise ExecutionError("Side must be BUY or SELL.")
    if quantity <= 0 or market_price <= 0:
        raise ExecutionError("Quantity and price must be positive.")

    costs = _costs(side, quantity, market_price)
    now = datetime.now(timezone.utc).isoformat()

    with connection() as conn:
        cash_before = cash_balance(conn, mandate_id)
        position = conn.execute(
            "SELECT * FROM positions WHERE mandate_id=? AND symbol=?",
            (mandate_id, symbol),
        ).fetchone()
        old_qty = float(position["quantity"]) if position else 0.0
        old_avg = float(position["average_cost"]) if position else 0.0

        if side == "BUY":
            cash_effect = -(quantity * costs["execution_price"] + costs["commission"])
            if cash_before + cash_effect < -0.01:
                raise ExecutionError("Insufficient virtual cash.")
            new_qty = old_qty + quantity
            new_avg = (
                (old_qty * old_avg + quantity * costs["execution_price"]) / new_qty
            )
        else:
            if quantity > old_qty + 1e-9:
                raise ExecutionError("Cannot sell more than the paper position.")
            proceeds = quantity * costs["execution_price"] - costs["commission"] - costs["regulatory"]
            cash_effect = proceeds
            new_qty = old_qty - quantity
            new_avg = old_avg if new_qty > 1e-9 else 0.0

        cash_after = cash_before + cash_effect
        cur = conn.execute(
            """INSERT INTO trades
            (mandate_id, timestamp, symbol, side, quantity, market_price, execution_price,
             gross_value, spread_cost, slippage_cost, commission, regulatory_fee,
             total_fees, net_cash_effect, rationale, decision_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mandate_id, now, symbol, side, quantity, market_price,
                costs["execution_price"], costs["gross"], costs["spread"],
                costs["slippage"], costs["commission"], costs["regulatory"],
                costs["total_fees"], cash_effect, rationale, decision_id
            ),
        )
        trade_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO cash_ledger
            (mandate_id, timestamp, event_type, amount, balance_after, reference)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (mandate_id, now, f"TRADE_{side}", cash_effect, cash_after, f"trade:{trade_id}"),
        )
        conn.execute(
            """INSERT INTO positions
            (mandate_id, symbol, quantity, average_cost, last_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(mandate_id, symbol) DO UPDATE SET
                quantity=excluded.quantity,
                average_cost=excluded.average_cost,
                last_price=excluded.last_price,
                updated_at=excluded.updated_at""",
            (mandate_id, symbol, new_qty, new_avg, market_price, now),
        )

    return ExecutionResult(
        trade_id=trade_id, mandate_id=mandate_id, symbol=symbol, side=side,
        quantity=quantity, execution_price=costs["execution_price"],
        total_fees=costs["total_fees"], cash_after=cash_after
    )
