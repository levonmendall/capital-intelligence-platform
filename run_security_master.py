"""Ingest and inspect security-master catalogs without bypassing activation policy."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from data import (
    SQLiteProviderCertificationStore,
    SQLiteSecurityMasterOperationalStore,
    SQLiteSecurityMasterStore,
    SecurityMasterActivationError,
    SecurityMasterActivationMode,
    SecurityMasterActivationPolicy,
    SecurityMasterIngestionQuery,
    SecurityMasterIngestionService,
    SecurityMasterProviderError,
)
from providers import SECEdgarProvider


def _database_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    data_dir = Path(
        os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATABASE",
            str(data_dir / "security_master.db"),
        )
    ).expanduser()


def _timestamp(value: str | None, *, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed


def _activation_mode(args: argparse.Namespace) -> SecurityMasterActivationMode:
    if args.store_only:
        return SecurityMasterActivationMode.STORE_ONLY
    if args.require_activation:
        return SecurityMasterActivationMode.REQUIRE_ACTIVATION
    return SecurityMasterActivationMode.ACTIVATE_IF_ELIGIBLE


def _service(path: Path, *, maximum_age_hours: float) -> SecurityMasterIngestionService:
    return SecurityMasterIngestionService(
        SQLiteSecurityMasterStore(path),
        SQLiteSecurityMasterOperationalStore(path),
        activation_policy=SecurityMasterActivationPolicy(
            maximum_catalog_age_hours=maximum_age_hours,
        ),
        certification_store=SQLiteProviderCertificationStore(path),
    )


def _result_payload(result) -> dict[str, object]:
    return {
        "identifier": result.identifier,
        "provider": result.provider,
        "catalog_identifier": result.catalog_identifier,
        "disposition": result.disposition.value,
        "activation_identifier": result.activation_identifier,
        "screening_ready": result.disposition.value == "activated",
        "quality": {
            "authoritative_coverage": result.quality.authoritative_coverage,
            "integrity_verified": result.quality.integrity_verified,
            "source_observed_at": result.quality.source_observed_at.isoformat(),
            "source_retrieved_at": result.quality.source_retrieved_at.isoformat(),
            "source_age_hours": result.quality.source_age_hours,
            "instrument_count": result.quality.instrument_count,
            "active_listing_ratio": result.quality.active_listing_ratio,
            "classified_instrument_ratio": (
                result.quality.classified_instrument_ratio
            ),
            "stable_identifier_ratio": result.quality.stable_identifier_ratio,
            "coverage_deficiencies": list(
                result.quality.coverage_deficiencies
            ),
            "certification_identifier": result.quality.certification_identifier,
            "certification_decision": result.quality.certification_decision,
            "certification_valid_until": (
                None
                if result.quality.certification_valid_until is None
                else result.quality.certification_valid_until.isoformat()
            ),
            "issues": list(result.quality.issues),
        },
    }


def _status_payload(status) -> dict[str, object]:
    latest = status.latest_ingestion
    activation = status.latest_activation
    return {
        "evaluated_at": status.evaluated_at.isoformat(),
        "screening_ready": status.screening_ready,
        "catalog_integrity_verified": status.catalog_integrity_verified,
        "operation_integrity_verified": status.operation_integrity_verified,
        "active_catalog_identifier": status.active_catalog_identifier,
        "active_source_age_hours": status.active_source_age_hours,
        "latest_ingestion": (
            None
            if latest is None
            else {
                "identifier": latest.identifier,
                "provider": latest.provider,
                "catalog_identifier": latest.catalog_identifier,
                "disposition": latest.disposition.value,
                "ingested_at": latest.ingested_at.isoformat(),
            }
        ),
        "latest_activation": (
            None
            if activation is None
            else {
                "identifier": activation.identifier,
                "catalog_identifier": activation.catalog_identifier,
                "activated_at": activation.activated_at.isoformat(),
                "policy_version": activation.policy_version,
            }
        ),
        "reasons": list(status.reasons),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest or inspect point-in-time security-master catalogs. "
            "The public SEC current feed is stored for discovery but cannot "
            "activate full-universe screening."
        )
    )
    parser.add_argument("--database", help="Override the security-master database path.")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report current catalog integrity, activation, freshness, and readiness.",
    )
    parser.add_argument(
        "--as-of",
        help="Economic timestamp in ISO-8601 form. Defaults to the run timestamp.",
    )
    parser.add_argument(
        "--store-only",
        action="store_true",
        help="Store the catalog without attempting activation.",
    )
    parser.add_argument(
        "--require-activation",
        action="store_true",
        help="Exit nonzero when the fetched catalog cannot be activated.",
    )
    parser.add_argument(
        "--maximum-age-hours",
        type=float,
        default=36.0,
        help="Maximum source-observation age allowed by activation policy.",
    )
    args = parser.parse_args(argv)
    if args.store_only and args.require_activation:
        parser.error("--store-only and --require-activation are mutually exclusive")
    if args.maximum_age_hours < 0:
        parser.error("--maximum-age-hours cannot be negative")

    now = datetime.now(timezone.utc)
    path = _database_path(args.database)
    service = _service(path, maximum_age_hours=args.maximum_age_hours)
    if args.status:
        print(json.dumps(_status_payload(service.status(evaluated_at=now)), indent=2))
        return 0

    as_of = _timestamp(args.as_of, default=now)
    if as_of > now:
        parser.error("--as-of cannot be in the future")
    provider = SECEdgarProvider(clock=lambda: now)
    if not provider.configured:
        parser.error(
            "SEC_USER_AGENT is required to retrieve the SEC current ticker feed"
        )
    query = SecurityMasterIngestionQuery(
        identifier=f"sec-edgar-current:{now.isoformat()}",
        as_of=as_of,
        knowledge_cutoff=now,
        requested_at=now,
        activation_mode=_activation_mode(args),
    )
    try:
        result = service.ingest(provider, query)
    except SecurityMasterActivationError as error:
        print(json.dumps(_result_payload(error.result), indent=2))
        return 3
    except SecurityMasterProviderError as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 2
    print(json.dumps(_result_payload(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
