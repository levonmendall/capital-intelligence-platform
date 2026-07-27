"""Compatibility seeding for the retired portfolio database."""

import json
from pathlib import Path

from core.database import get_connection, initialize_database

ROOT = Path(__file__).resolve().parent.parent
MANDATES_FILE = ROOT / "config" / "mandates.json"


def seed_mandates() -> int:
    """Insert only the legacy-compatible compounding portfolio record."""

    initialize_database()

    with MANDATES_FILE.open("r", encoding="utf-8") as file:
        mandates = json.load(file)

    with get_connection() as connection:
        for mandate in mandates:
            capital = float(mandate["capital"])

            connection.execute(
                """
                INSERT OR IGNORE INTO mandates (
                    code,
                    name,
                    risk,
                    starting_capital,
                    cash,
                    nav
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mandate["code"],
                    mandate["name"],
                    mandate["risk"],
                    capital,
                    capital,
                    capital,
                ),
            )

        result = connection.execute(
            "SELECT COUNT(*) AS count FROM mandates"
        ).fetchone()

    return int(result["count"])
