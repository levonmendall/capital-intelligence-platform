"""Initialize active Capital Intelligence data stores and binding market scope."""

from api.config import ApiSettings
from market_scope import load_global_market_scope
from portfolio.constants import (
    CANONICAL_PORTFOLIO_CODE,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.state import ensure_canonical_portfolio_store


def main() -> None:
    print("Initializing Capital Intelligence Platform...")
    settings = ApiSettings.from_env()
    scope = load_global_market_scope()
    scope.require_complete_analysis_scope()
    result = ensure_canonical_portfolio_store(settings.portfolio_database)
    print(
        f"Canonical portfolio {CANONICAL_PORTFOLIO_CODE} initialized at "
        f"{settings.portfolio_database} with ${INITIAL_PAPER_CAPITAL:,.2f}."
    )
    if result.archive_path is not None:
        print(f"Legacy paper history archived at {result.archive_path}.")
    print(
        f"Global market analysis scope validated across "
        f"{len(scope.markets)} governed market families."
    )


if __name__ == "__main__":
    main()
