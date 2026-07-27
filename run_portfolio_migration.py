"""Migrate only the legacy COMPOUNDING portfolio into canonical state.

Retired mandate rows remain in the read-only legacy database as audit evidence.
They are never imported as active portfolios.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from portfolio.constants import (
    CANONICAL_PORTFOLIO_CODE,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.state import (
    CanonicalImplementationEvent,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)


def _legacy_connection(path: Path) -> sqlite3.Connection:
    if not path.exists() or not path.is_file():
        raise ValueError(f"legacy portfolio database is unavailable: {path}")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def migrate(*, legacy_path: Path, canonical_path: Path, as_of: datetime) -> int:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    store = SQLiteCanonicalPortfolioStore(canonical_path)
    store.verify_integrity()
    if store.list_latest():
        raise ValueError("canonical portfolio database must be empty before migration")

    with _legacy_connection(legacy_path) as connection:
        mandates = connection.execute(
            """
            SELECT code, name, risk, starting_capital, cash
            FROM mandates
            WHERE UPPER(TRIM(code)) = ?
            ORDER BY id
            """,
            (CANONICAL_PORTFOLIO_CODE,),
        ).fetchall()
        if len(mandates) != 1:
            raise ValueError(
                "legacy database must contain exactly one COMPOUNDING mandate to migrate"
            )
        mandate = mandates[0]
        starting_capital = float(mandate["starting_capital"])
        if abs(starting_capital - INITIAL_PAPER_CAPITAL) > 0.00000001:
            raise ValueError(
                "legacy COMPOUNDING starting capital must be $250,000.00; "
                "archive the legacy database and initialize a clean portfolio instead"
            )

        positions = tuple(
            CanonicalPortfolioPosition(
                symbol=str(row["symbol"]),
                quantity=float(row["quantity"]),
                average_cost=float(row["average_cost"]),
                mark_price=float(row["current_price"]),
                updated_at=datetime.fromisoformat(
                    str(row["updated_at"]).replace("Z", "+00:00")
                ),
            )
            for row in connection.execute(
                """
                SELECT symbol, quantity, average_cost, current_price, updated_at
                FROM holdings
                WHERE UPPER(TRIM(mandate_code)) = ?
                ORDER BY symbol
                """,
                (CANONICAL_PORTFOLIO_CODE,),
            ).fetchall()
        )
        events = tuple(
            CanonicalImplementationEvent(
                identifier=f"legacy-trade:{row['id']}",
                occurred_at=datetime.fromisoformat(
                    str(row["created_at"]).replace("Z", "+00:00")
                ),
                action=str(row["side"]),
                symbol=str(row["symbol"]),
                quantity=float(row["quantity"]),
                price=float(row["price"]),
                gross_amount=float(row["gross_amount"]),
                rationale=str(row["rationale"]),
                source_identifier="legacy-portfolio-migration",
            )
            for row in connection.execute(
                """
                SELECT id, created_at, side, symbol, quantity, price,
                       gross_amount, rationale
                FROM trades
                WHERE UPPER(TRIM(mandate_code)) = ?
                ORDER BY id
                """,
                (CANONICAL_PORTFOLIO_CODE,),
            ).fetchall()
        )
        snapshot = CanonicalPortfolioSnapshot(
            identifier=(
                "portfolio-migration:COMPOUNDING:"
                f"{as_of.astimezone(timezone.utc).isoformat()}"
            ),
            portfolio_code=CANONICAL_PORTFOLIO_CODE,
            display_name=str(mandate["name"]),
            constraint_profile=str(mandate["risk"]),
            as_of=as_of,
            starting_capital=starting_capital,
            cash_amount=float(mandate["cash"]),
            positions=positions,
            implementation_events=events,
            source_identifiers=(f"legacy-database:{legacy_path.name}",),
        )
        store.append(snapshot)

    store.verify_integrity()
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-db", required=True)
    parser.add_argument("--canonical-db", default="database/canonical_portfolio.db")
    parser.add_argument("--as-of", required=True, help="Timezone-aware migration cutoff")
    args = parser.parse_args(argv)
    try:
        as_of = datetime.fromisoformat(args.as_of)
        count = migrate(
            legacy_path=Path(args.legacy_db),
            canonical_path=Path(args.canonical_db),
            as_of=as_of,
        )
    except (ValueError, TypeError, sqlite3.Error) as error:
        print(f"migration failed: {error}")
        return 4
    print(f"migrated {count} canonical portfolio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
