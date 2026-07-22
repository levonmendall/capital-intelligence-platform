from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os
DEFAULT_DB_PATH = ROOT / "database" / "cio_paper_funds.db"

def database_path() -> Path:
    return Path(os.environ.get("AI_CIO_DB_PATH", DEFAULT_DB_PATH))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mandates (
    mandate_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    inception_date TEXT NOT NULL,
    starting_capital REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandate_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    reference TEXT,
    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id)
);

CREATE TABLE IF NOT EXISTS positions (
    mandate_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 0,
    average_cost REAL NOT NULL DEFAULT 0,
    last_price REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (mandate_id, symbol),
    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id)
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandate_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    quantity REAL NOT NULL,
    market_price REAL NOT NULL,
    execution_price REAL NOT NULL,
    gross_value REAL NOT NULL,
    spread_cost REAL NOT NULL,
    slippage_cost REAL NOT NULL,
    commission REAL NOT NULL,
    regulatory_fee REAL NOT NULL,
    total_fees REAL NOT NULL,
    net_cash_effect REAL NOT NULL,
    rationale TEXT,
    decision_id INTEGER,
    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id)
);

CREATE TABLE IF NOT EXISTS nav_history (
    mandate_id TEXT NOT NULL,
    valuation_date TEXT NOT NULL,
    cash REAL NOT NULL,
    securities_value REAL NOT NULL,
    accrued_expenses REAL NOT NULL DEFAULT 0,
    nav REAL NOT NULL,
    benchmark_value REAL,
    PRIMARY KEY (mandate_id, valuation_date),
    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id)
);

CREATE TABLE IF NOT EXISTS cio_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    regime TEXT NOT NULL,
    confidence REAL NOT NULL,
    market_view_json TEXT NOT NULL,
    target_allocations_json TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    source TEXT NOT NULL,
    signals_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intelligence_decisions (
    intelligence_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    primary_regime TEXT NOT NULL,
    confidence REAL NOT NULL,
    composite_risk_score REAL NOT NULL,
    decision_json TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES market_snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS council_opinions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intelligence_decision_id INTEGER NOT NULL,
    specialist_id TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    recommendation TEXT NOT NULL,
    opinion_json TEXT NOT NULL,
    FOREIGN KEY(intelligence_decision_id) REFERENCES intelligence_decisions(intelligence_decision_id)
);

CREATE TABLE IF NOT EXISTS opportunity_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intelligence_decision_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    rank INTEGER NOT NULL,
    opportunity_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    score_json TEXT NOT NULL,
    FOREIGN KEY(intelligence_decision_id) REFERENCES intelligence_decisions(intelligence_decision_id)
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    decision_id INTEGER
);
"""

@contextmanager
def connection():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def initialize_schema() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
