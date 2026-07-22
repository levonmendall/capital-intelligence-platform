
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "capital_rotation_v21.db"
HISTORY_DIR = ROOT / "data" / "history"
MARKET_HISTORY_CSV = HISTORY_DIR / "market_history.csv"
REGIME_HISTORY_CSV = HISTORY_DIR / "regime_history.csv"
ROTATION_HISTORY_CSV = HISTORY_DIR / "rotation_history.csv"
DECISION_OUTCOMES_CSV = HISTORY_DIR / "decision_outcomes.csv"


def ensure_history_dir() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_history_dir()
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS market_history(
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            group_name TEXT,
            level TEXT,
            price REAL,
            move_1d REAL,
            momentum_3m REAL,
            momentum_12m REAL,
            breadth REAL,
            flow REAL,
            risk_score REAL,
            volatility REAL,
            source TEXT,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(date, ticker)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS regime_history(
            date TEXT PRIMARY KEY,
            regime TEXT,
            posture TEXT,
            confidence REAL,
            risk_score REAL,
            composite REAL,
            growth REAL,
            liquidity REAL,
            breadth REAL,
            credit REAL,
            volatility_safety REAL,
            payload TEXT,
            recorded_at TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS rotation_history(
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            group_name TEXT,
            level TEXT,
            rank INTEGER,
            risk_adjusted_score REAL,
            trend_score REAL,
            cio_view TEXT,
            trend TEXT,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(date, ticker)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS committee_history(
            date TEXT NOT NULL,
            specialist TEXT NOT NULL,
            score REAL,
            view TEXT,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(date, specialist)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS decision_history(
            date TEXT PRIMARY KEY,
            regime TEXT,
            posture TEXT,
            confidence REAL,
            risk_score REAL,
            increase_asset TEXT,
            maintain_asset TEXT,
            reduce_asset TEXT,
            specialist_agreement REAL,
            brief TEXT,
            payload TEXT,
            recorded_at TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS decision_outcomes(
            decision_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            horizon_days INTEGER NOT NULL,
            forward_return REAL,
            benchmark_return REAL,
            relative_return REAL,
            outcome_status TEXT,
            calculated_at TEXT NOT NULL,
            PRIMARY KEY(decision_date, ticker, horizon_days)
        )
    """)
    con.commit()
    return con


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_string(value=None) -> str:
    if value is None:
        return datetime.now(timezone.utc).date().isoformat()
    return pd.Timestamp(value).date().isoformat()


def append_daily_state(
    market: pd.DataFrame,
    regime: dict,
    specialists: pd.DataFrame,
    decision: dict,
    as_of_date=None,
    source: str = "daily_refresh",
) -> None:
    """Persist one immutable daily state in SQLite and synchronized CSV exports."""
    from engine import enrich_market

    ensure_history_dir()
    as_of = _date_string(as_of_date)
    recorded_at = _utc_now()
    enriched = enrich_market(market)

    with connect() as con:
        for _, row in enriched.iterrows():
            con.execute("""
                INSERT OR REPLACE INTO market_history(
                    date,ticker,group_name,level,price,move_1d,momentum_3m,
                    momentum_12m,breadth,flow,risk_score,volatility,source,recorded_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                as_of, str(row["ticker"]), str(row["group"]), str(row["level"]),
                float(row.get("price", 0)), float(row.get("move_1d", 0)),
                float(row.get("momentum_3m", 0)), float(row.get("momentum_12m", 0)),
                float(row.get("breadth", 0)), float(row.get("flow", 0)),
                float(row.get("risk_score", 0)), float(row.get("volatility", 0)),
                source, recorded_at,
            ))
            con.execute("""
                INSERT OR REPLACE INTO rotation_history(
                    date,ticker,group_name,level,rank,risk_adjusted_score,
                    trend_score,cio_view,trend,recorded_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                as_of, str(row["ticker"]), str(row["group"]), str(row["level"]),
                int(row["rank"]), float(row["risk_adjusted_score"]),
                float(row["trend_score"]), str(row["cio_view"]), str(row["trend"]),
                recorded_at,
            ))

        c = regime["components"]
        con.execute("""
            INSERT OR REPLACE INTO regime_history(
                date,regime,posture,confidence,risk_score,composite,growth,
                liquidity,breadth,credit,volatility_safety,payload,recorded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            as_of, regime["regime"], regime["posture"], float(regime["confidence"]),
            float(regime["risk_score"]), float(regime["composite"]),
            float(c["Growth"]), float(c["Liquidity"]), float(c["Breadth"]),
            float(c["Credit"]), float(c["Volatility safety"]),
            json.dumps(regime), recorded_at,
        ))

        for _, row in specialists.iterrows():
            con.execute("""
                INSERT OR REPLACE INTO committee_history(
                    date,specialist,score,view,recorded_at
                ) VALUES(?,?,?,?,?)
            """, (
                as_of, str(row["specialist"]), float(row["score"]),
                str(row["view"]), recorded_at,
            ))

        con.execute("""
            INSERT OR REPLACE INTO decision_history(
                date,regime,posture,confidence,risk_score,increase_asset,
                maintain_asset,reduce_asset,specialist_agreement,brief,payload,recorded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            as_of, decision["regime"], decision["posture"],
            float(decision["confidence"]), float(decision["risk_score"]),
            str(decision["increase"]), str(decision["maintain"]), str(decision["reduce"]),
            float(decision["specialist_agreement"]), str(decision["brief"]),
            json.dumps(decision), recorded_at,
        ))
        con.commit()

    export_history_csvs()


def export_history_csvs() -> None:
    ensure_history_dir()
    with connect() as con:
        pd.read_sql_query(
            "SELECT * FROM market_history ORDER BY date,ticker", con
        ).to_csv(MARKET_HISTORY_CSV, index=False)
        pd.read_sql_query(
            "SELECT * FROM regime_history ORDER BY date", con
        ).to_csv(REGIME_HISTORY_CSV, index=False)
        pd.read_sql_query(
            "SELECT * FROM rotation_history ORDER BY date,rank", con
        ).to_csv(ROTATION_HISTORY_CSV, index=False)
        pd.read_sql_query(
            "SELECT * FROM decision_outcomes ORDER BY decision_date,horizon_days,ticker", con
        ).to_csv(DECISION_OUTCOMES_CSV, index=False)


def load_history(table: str, limit: int | None = None) -> pd.DataFrame:
    allowed = {
        "market_history", "regime_history", "rotation_history",
        "committee_history", "decision_history", "decision_outcomes",
    }
    if table not in allowed:
        raise ValueError(f"Unsupported history table: {table}")
    query = f"SELECT * FROM {table} ORDER BY date" if table != "decision_outcomes" else (
        "SELECT * FROM decision_outcomes ORDER BY decision_date"
    )
    with connect() as con:
        df = pd.read_sql_query(query, con)
    if limit:
        return df.tail(limit)
    return df


def seed_database_from_csvs() -> None:
    """Restore the local SQLite database from committed CSV history files."""
    ensure_history_dir()
    with connect() as con:
        if MARKET_HISTORY_CSV.exists():
            df = pd.read_csv(MARKET_HISTORY_CSV)
            df.to_sql("market_history", con, if_exists="replace", index=False)
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_day_ticker ON market_history(date,ticker)")
        if REGIME_HISTORY_CSV.exists():
            df = pd.read_csv(REGIME_HISTORY_CSV)
            df.to_sql("regime_history", con, if_exists="replace", index=False)
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_regime_day ON regime_history(date)")
        if ROTATION_HISTORY_CSV.exists():
            df = pd.read_csv(ROTATION_HISTORY_CSV)
            df.to_sql("rotation_history", con, if_exists="replace", index=False)
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rotation_day_ticker ON rotation_history(date,ticker)")
        if DECISION_OUTCOMES_CSV.exists():
            df = pd.read_csv(DECISION_OUTCOMES_CSV)
            df.to_sql("decision_outcomes", con, if_exists="replace", index=False)
        con.commit()


def regime_duration(regime_history: pd.DataFrame) -> int:
    if regime_history.empty:
        return 0
    ordered = regime_history.sort_values("date")
    current = ordered.iloc[-1]["regime"]
    count = 0
    for value in reversed(ordered["regime"].tolist()):
        if value != current:
            break
        count += 1
    return count


def transition_matrix(regime_history: pd.DataFrame) -> pd.DataFrame:
    if len(regime_history) < 2:
        return pd.DataFrame()
    ordered = regime_history.sort_values("date")
    transitions = pd.crosstab(
        ordered["regime"].shift(1),
        ordered["regime"],
        normalize="index",
    ) * 100
    return transitions.round(1)


def rotation_forward_performance(
    market_history: pd.DataFrame,
    rotation_history: pd.DataFrame,
    horizon_days: int = 21,
    top_n: int = 3,
) -> pd.DataFrame:
    if market_history.empty or rotation_history.empty:
        return pd.DataFrame()
    prices = market_history.pivot(index="date", columns="ticker", values="price").sort_index()
    dates = list(prices.index)
    rows = []
    for i, date in enumerate(dates):
        end_index = i + horizon_days
        if end_index >= len(dates):
            continue
        leaders = rotation_history[
            (rotation_history["date"].astype(str) == str(date)) &
            (rotation_history["rank"] <= top_n)
        ]
        for _, leader in leaders.iterrows():
            ticker = leader["ticker"]
            if ticker not in prices.columns:
                continue
            start = prices.loc[date, ticker]
            end = prices.iloc[end_index][ticker]
            if pd.isna(start) or pd.isna(end) or start == 0:
                continue
            rows.append({
                "decision_date": date,
                "ticker": ticker,
                "rank": int(leader["rank"]),
                "horizon_days": horizon_days,
                "forward_return": float(end / start - 1),
            })
    return pd.DataFrame(rows)


def historical_summary() -> dict:
    try:
        regimes = load_history("regime_history")
        rotations = load_history("rotation_history")
        markets = load_history("market_history")
    except Exception:
        return {
            "history_days": 0, "first_date": None, "last_date": None,
            "regime_changes": 0, "current_regime_days": 0,
            "tracked_assets": 0,
        }
    changes = 0
    if not regimes.empty:
        changes = int((regimes["regime"] != regimes["regime"].shift()).sum() - 1)
    return {
        "history_days": int(regimes["date"].nunique()) if not regimes.empty else 0,
        "first_date": regimes["date"].min() if not regimes.empty else None,
        "last_date": regimes["date"].max() if not regimes.empty else None,
        "regime_changes": max(changes, 0),
        "current_regime_days": regime_duration(regimes),
        "tracked_assets": int(markets["ticker"].nunique()) if not markets.empty else 0,
    }
