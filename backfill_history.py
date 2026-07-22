
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from engine import enrich_market, regime_engine, specialist_committee, build_decision
from historical_engine import append_daily_state, export_history_csvs
from storage import log_refresh

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "current_snapshot.csv"
HOLDINGS = ROOT / "portfolio_holdings.csv"


def _series_from_download(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        for price_field in ("Close", "Adj Close"):
            try:
                return raw[ticker][price_field].dropna()
            except Exception:
                pass
            try:
                return raw[price_field][ticker].dropna()
            except Exception:
                pass
    for price_field in ("Close", "Adj Close"):
        if price_field in raw.columns:
            return raw[price_field].dropna()
    return pd.Series(dtype=float)


def _feature_at(series: pd.Series, location: int) -> dict:
    window = series.iloc[: location + 1]
    price = float(window.iloc[-1])
    move_1d = float((window.iloc[-1] / window.iloc[-2] - 1) * 100) if len(window) >= 2 else 0.0
    mom_3m = float((window.iloc[-1] / window.iloc[-63] - 1) * 100) if len(window) >= 63 else 0.0
    mom_12m = float((window.iloc[-1] / window.iloc[-252] - 1) * 100) if len(window) >= 252 else 0.0
    volatility = float(window.pct_change().dropna().tail(63).std() * np.sqrt(252) * 100) if len(window) >= 21 else 0.0

    ma50 = window.tail(50).mean() if len(window) >= 20 else price
    ma200 = window.tail(200).mean() if len(window) >= 50 else price
    breadth = float(np.clip(50 + ((price / ma50) - 1) * 500 + ((price / ma200) - 1) * 250, 0, 100))
    flow = float(np.clip(50 + mom_3m * 2.5 - volatility * 0.35, 0, 100))
    risk_score = float(np.clip(100 - volatility * 1.7 + max(mom_3m, -10), 0, 100))

    return {
        "price": price,
        "move_1d": move_1d,
        "momentum_3m": mom_3m,
        "momentum_12m": mom_12m,
        "breadth": breadth,
        "flow": flow,
        "risk_score": risk_score,
        "volatility": volatility,
    }


def run_backfill(period: str = "10y", frequency: str = "W-FRI") -> None:
    template = pd.read_csv(SNAPSHOT)
    tickers = [str(t) for t in template["ticker"] if str(t) != "CASH"]
    raw = yf.download(
        tickers,
        period=period,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    series_map = {ticker: _series_from_download(raw, ticker) for ticker in tickers}
    series_map = {k: v for k, v in series_map.items() if not v.empty}
    if not series_map:
        raise RuntimeError("No historical price series were downloaded.")

    common_dates = sorted(set().union(*[set(s.index) for s in series_map.values()]))
    date_index = pd.DatetimeIndex(common_dates)
    sampled_dates = pd.Series(index=date_index, data=date_index).resample(frequency).last().dropna().tolist()

    portfolio_summary = {"concentration": 0.0}
    completed = 0
    for date in sampled_dates:
        rows = []
        for _, template_row in template.iterrows():
            row = template_row.copy()
            ticker = str(row["ticker"])
            if ticker == "CASH":
                row["price"] = 1.0
                row["move_1d"] = 0.0
                row["momentum_3m"] = 0.0
                row["momentum_12m"] = 0.0
                row["breadth"] = 50.0
                row["flow"] = 50.0
                row["risk_score"] = 98.0
                row["volatility"] = 0.1
                rows.append(row)
                continue
            series = series_map.get(ticker)
            if series is None:
                continue
            eligible = series.loc[:date]
            if eligible.empty:
                continue
            location = len(eligible) - 1
            features = _feature_at(eligible, location)
            for key, value in features.items():
                row[key] = value
            rows.append(row)

        day_market = pd.DataFrame(rows)
        if len(day_market) < 3:
            continue
        enriched = enrich_market(day_market)
        regime = regime_engine(enriched)
        committee = specialist_committee(enriched, regime)
        decision = build_decision(enriched, regime, committee, portfolio_summary)
        append_daily_state(
            day_market,
            regime,
            committee,
            decision,
            as_of_date=date,
            source=f"historical_backfill_{period}_{frequency}",
        )
        completed += 1
        if completed % 25 == 0:
            print(f"Archived {completed} historical decision dates...")

    export_history_csvs()
    message = f"Historical backfill completed: {completed} dates using period={period}, frequency={frequency}"
    log_refresh("success", message)
    print(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="10y")
    parser.add_argument("--frequency", default="W-FRI")
    args = parser.parse_args()
    run_backfill(args.period, args.frequency)
