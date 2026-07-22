from core.database import connection, initialize_schema
from core.seed import seed_mandates

def test_eight_mandates_seeded():
    initialize_schema()
    seed_mandates()
    with connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM mandates").fetchone()["n"]
        capital = conn.execute("SELECT SUM(starting_capital) AS n FROM mandates").fetchone()["n"]
    assert count == 8
    assert capital == 200000
