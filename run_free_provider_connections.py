"""Verify and persist connectivity for every configured free public provider."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from providers.free_connections import (
    FreeProviderConnectionError,
    FreeProviderConnectionVerifier,
    SQLiteFreeProviderConnectionStore,
    load_free_provider_catalog,
)


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_FREE_PROVIDER_CATALOG",
            "config/free_provider_connections.json",
        ),
    )
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_FREE_PROVIDER_DATABASE",
            str(data_dir / "free_provider_connections.db"),
        ),
    )
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument(
        "--require-all-connected",
        action="store_true",
        help="Return a blocking status unless every enabled service is connected.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SQLiteFreeProviderConnectionStore(args.database)
    try:
        if args.status:
            report = store.latest()
            print(
                json.dumps(
                    {
                        "status": "unavailable" if report is None else "available",
                        "report": None if report is None else report.to_dict(),
                    },
                    sort_keys=True,
                )
            )
            return 0 if report is not None else 2

        catalog = load_free_provider_catalog(args.catalog)
        report = FreeProviderConnectionVerifier(
            catalog,
            repository_root=args.repository_root,
        ).verify()
        sequence = None if args.no_persist else store.append(report)
        print(
            json.dumps(
                {
                    "sequence": sequence,
                    "report": report.to_dict(),
                },
                sort_keys=True,
            )
        )
        if args.require_all_connected and not report.all_enabled_connected:
            return 3
        return 0
    except (OSError, TypeError, ValueError, FreeProviderConnectionError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "provider_certification_granted": False,
                    "paper_test_readiness_granted": False,
                    "execution_authority_granted": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
