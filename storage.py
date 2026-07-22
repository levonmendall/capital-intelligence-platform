
from pathlib import Path
import sqlite3, json
import pandas as pd
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DB = ROOT / "capital_rotation_v2.db"

def connect():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS decisions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        regime TEXT,
        posture TEXT,
        confidence REAL,
        risk_score REAL,
        brief TEXT,
        payload TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS refresh_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        status TEXT,
        message TEXT
    )""")
    con.commit()
    return con

def save_decision(decision):
    with connect() as con:
        con.execute(
            "INSERT INTO decisions(created_at,regime,posture,confidence,risk_score,brief,payload) VALUES(?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), decision["regime"], decision["posture"],
             decision["confidence"], decision["risk_score"], decision["brief"], json.dumps(decision))
        )

def decision_history(limit=100):
    with connect() as con:
        return pd.read_sql_query("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", con, params=(limit,))

def log_refresh(status, message):
    with connect() as con:
        con.execute("INSERT INTO refresh_log(created_at,status,message) VALUES(?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), status, message))

def refresh_history(limit=50):
    with connect() as con:
        return pd.read_sql_query("SELECT * FROM refresh_log ORDER BY id DESC LIMIT ?", con, params=(limit,))


def initialize_v21_history():
    """Initialize or restore the V2.1 historical database."""
    try:
        from historical_engine import connect as history_connect, seed_database_from_csvs
        history_connect().close()
        seed_database_from_csvs()
    except Exception:
        # The live dashboard can still run from the current snapshot if history is unavailable.
        pass
