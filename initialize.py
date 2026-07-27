"""Initialize active Capital Intelligence data stores."""

from api.config import ApiSettings
from portfolio.state import SQLiteCanonicalPortfolioStore


def main() -> None:
    print("Initializing Capital Intelligence Platform...")
    settings = ApiSettings.from_env()
    store = SQLiteCanonicalPortfolioStore(settings.portfolio_database)
    store.verify_integrity()
    print(f"Canonical portfolio state initialized at {settings.portfolio_database}.")


if __name__ == "__main__":
    main()
