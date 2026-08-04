"""Collect maximum immediately usable public live information safely."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from providers.public_live_source_catalogs import load_operating_public_live_source_catalog
from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)


def _default_catalog() -> str:
    return os.getenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_SOURCE_CATALOG",
        "config/public_live_information_sources.json",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=_default_catalog())
    parser.add_argument("--output", help="Credential-safe coverage report JSON path.")
    parser.add_argument(
        "--records-output",
        help="Normalized point-in-time records JSON path; contains metadata, not article bodies.",
    )
    parser.add_argument(
        "--required-only",
        action="store_true",
        help="Skip optional sources that require additional free or paid credentials.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON.",
    )
    return parser


def _write(path: str, payload: Mapping[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_operating_public_live_source_catalog(args.catalog)
        report = ImpactfulPublicLiveInformationProvider(catalog).collect(
            include_optional=not args.required_only
        )
        payload = report.to_dict(include_records=False)
        if args.output:
            _write(args.output, payload)
        if args.records_output:
            _write(
                args.records_output,
                {
                    "schema_version": "public-live-information-record-set.v1",
                    "catalog_identifier": report.catalog_identifier,
                    "evaluated_at": report.evaluated_at.isoformat(),
                    "records": [item.to_dict() for item in report.records],
                    "full_article_text_stored": False,
                    "secret_values_disclosed": False,
                    "real_money_authorized": False,
                },
            )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error": str(error),
                    "secret_values_disclosed": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4

    print(
        json.dumps(
            payload,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    if not report.required_sources_ready:
        return 3
    if any(not item.succeeded for item in report.sources):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
