
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

from engine import (
    enrich_market,
    regime_engine,
    specialist_committee,
    portfolio_analysis,
    build_decision,
)
from historical_engine import append_daily_state
from storage import log_refresh

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "current_snapshot.csv"
HOLDINGS = ROOT / "portfolio_holdings.csv"


def _close_series(raw, ticker):
    if isinstance(raw.columns, pd.MultiIndex):
        for field in ("Close", "Adj Close"):
            try:
                return raw[ticker][field].dropna()
            except Exception:
                pass
            try:
                return raw[field][ticker].dropna()
            except Exception:
                pass
    for field in ("Close", "Adj Close"):
        if field in raw.columns:
            return raw[field].dropna()
    return pd.Series(dtype=float)


def refresh():
    df = pd.read_csv(SNAPSHOT)
    tickers = [str(t) for t in df["ticker"] if str(t) != "CASH"]
    try:
        px = yf.download(
            tickers,
            period="18mo",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
        rows = []
        for _, original in df.iterrows():
            r = original.copy()
            ticker = str(r["ticker"])
            if ticker == "CASH":
                rows.append(r)
                continue
            series = _close_series(px, ticker)
            if len(series) >= 2:
                r["price"] = float(series.iloc[-1])
                r["move_1d"] = float((series.iloc[-1] / series.iloc[-2] - 1) * 100)
            if len(series) >= 63:
                r["momentum_3m"] = float((series.iloc[-1] / series.iloc[-63] - 1) * 100)
            if len(series) >= 252:
                r["momentum_12m"] = float((series.iloc[-1] / series.iloc[-252] - 1) * 100)
            if len(series) >= 21:
                r["volatility"] = float(series.pct_change().dropna().tail(63).std() * 252**0.5 * 100)
            rows.append(r)

        out = pd.DataFrame(rows)
        out.to_csv(SNAPSHOT, index=False)

        enriched = enrich_market(out)
        regime = regime_engine(enriched)
        committee = specialist_committee(enriched, regime)

        holdings = pd.read_csv(HOLDINGS) if HOLDINGS.exists() else pd.DataFrame(
            columns=["ticker","description","market_value","cost_basis","account_type","max_weight"]
        )
        _, portfolio_summary = portfolio_analysis(holdings, enriched)
        decision = build_decision(enriched, regime, committee, portfolio_summary)

        append_daily_state(
            out,
            regime,
            committee,
            decision,
            source="daily_market_refresh",
        )

        message = (
            f"Updated and archived {len(out)} market groups at "
            f"{datetime.now(timezone.utc).isoformat()}"
        )
        log_refresh("success", message)
        print(message)
    except Exception as exc:
        log_refresh("failed", str(exc))
        raise


if __name__ == "__main__":
    refresh()
