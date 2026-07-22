from __future__ import annotations
from core.config_loader import mandates, settings
from core.database import connection, initialize_schema

def seed_mandates() -> int:
    initialize_schema()
    cfg = mandates()
    inception = settings()["inception_date"]
    created = 0
    with connection() as conn:
        for mandate_id, mandate in cfg.items():
            exists = conn.execute(
                "SELECT 1 FROM mandates WHERE mandate_id = ?", (mandate_id,)
            ).fetchone()
            if exists:
                continue
            capital = float(mandate["starting_capital"])
            conn.execute(
                """INSERT INTO mandates
                (mandate_id, display_name, benchmark, risk_level, inception_date, starting_capital)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    mandate_id, mandate["display_name"], mandate["benchmark"],
                    mandate["risk_level"], inception, capital
                ),
            )
            conn.execute(
                """INSERT INTO cash_ledger
                (mandate_id, timestamp, event_type, amount, balance_after, reference)
                VALUES (?, ?, 'INITIAL_CAPITAL', ?, ?, 'V3_SPRINT1_SEED')""",
                (mandate_id, f"{inception}T09:30:00-07:00", capital, capital),
            )
            conn.execute(
                """INSERT INTO nav_history
                (mandate_id, valuation_date, cash, securities_value, accrued_expenses, nav, benchmark_value)
                VALUES (?, ?, ?, 0, 0, ?, ?)""",
                (mandate_id, inception, capital, capital, capital),
            )
            created += 1
    return created

if __name__ == "__main__":
    count = seed_mandates()
    print(f"Seeded {count} mandates.")
