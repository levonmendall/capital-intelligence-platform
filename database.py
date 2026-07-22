from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "database" / "cio_paper_funds.db"

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
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def initialize_schema() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
