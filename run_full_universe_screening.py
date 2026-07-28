"""Run one certified, complete, resumable Version 1 universe screening cycle."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from api.config import ApiSettings
from cio.persistence import SQLiteCIOJournal
from data import (
    SQLiteProviderCertificationStore,
    SQLiteSecurityMasterOperationalStore,
    SQLiteSecurityMasterStore,
    SecurityMasterActivationPolicy,
    SecurityMasterIngestionService,
)
from operations import OperationalSettings, SQLiteOperationalSLOStore
from opportunity import AlternativeKind, AlternativeUse, OpportunitySetContext
from providers import (
    build_configured_candidate_screening_provider,
    build_configured_universe_metrics_provider,
)
from screening import (
    FullUniverseScreeningError,
    FullUniverseScreeningOrchestrator,
    FullUniverseScreeningRequest,
    SQLiteFullUniverseScreeningStore,
)


def _timestamp(value: str | None, *, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed


def _factory(value: str):
    if ":" not in value:
        raise ValueError("provider factories must use module:function form")
    module_name, attribute_name = value.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise ValueError(f"provider factory {value!r} is not callable")
    return factory()




def _metrics_provider(reference: str | None):
    if reference:
        return _factory(reference)
    if os.getenv("CAPITAL_INTELLIGENCE_UNIVERSE_METRICS_DATASET_BINDING"):
        return build_configured_universe_metrics_provider()
    raise ValueError(
        "configure --metrics-provider or "
        "CAPITAL_INTELLIGENCE_UNIVERSE_METRICS_DATASET_BINDING"
    )


def _candidate_provider(reference: str | None):
    if reference:
        return _factory(reference)
    if os.getenv("CAPITAL_INTELLIGENCE_CANDIDATE_SCREENING_DATASET_BINDING"):
        return build_configured_candidate_screening_provider()
    raise ValueError(
        "configure --candidate-provider or "
        "CAPITAL_INTELLIGENCE_CANDIDATE_SCREENING_DATASET_BINDING"
    )

def _context(payload: Mapping[str, Any]) -> OpportunitySetContext:
    alternatives = tuple(
        AlternativeUse(
            identifier=str(item["identifier"]),
            kind=AlternativeKind(str(item["kind"])),
            expected_return=float(item["expected_return"]),
            implementation_cost_return=float(item["implementation_cost_return"]),
            evidence_quality=float(item["evidence_quality"]),
            liquidity_score=float(item["liquidity_score"]),
            current_weight=float(item.get("current_weight", 0.0)),
        )
        for item in payload["alternatives"]
    )
    return OpportunitySetContext(
        identifier=str(payload["identifier"]),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        alternatives=alternatives,
    )


def _path(value: str | None, *, default: Path) -> Path:
    return default if value is None else Path(value).expanduser()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one complete Version 1 universe screening cycle. The command "
            "fails closed unless a currently certified authoritative security-"
            "master catalog is active, all point-in-time metrics are present, "
            "and every eligible instrument reaches a terminal result."
        )
    )
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--scheduled-for", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--knowledge-cutoff", required=True)
    parser.add_argument("--started-at")
    parser.add_argument("--context", required=True, help="Opportunity-context JSON file.")
    parser.add_argument(
        "--metrics-provider",
        help=(
            "Optional no-argument metrics-provider factory in module:function form. "
            "When omitted, the configured dataset binding is used."
        ),
    )
    parser.add_argument(
        "--candidate-provider",
        help=(
            "Optional no-argument candidate-provider factory in module:function "
            "form. When omitted, the configured dataset binding is used."
        ),
    )
    parser.add_argument("--partition-size", type=int, default=250)
    parser.add_argument("--maximum-partition-attempts", type=int, default=3)
    parser.add_argument("--security-master-database")
    parser.add_argument("--screening-database")
    parser.add_argument("--slo-database")
    parser.add_argument("--journal-database")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        scheduled_for = _timestamp(args.scheduled_for, default=now)
        as_of = _timestamp(args.as_of, default=now)
        knowledge_cutoff = _timestamp(args.knowledge_cutoff, default=now)
        started_at = _timestamp(args.started_at, default=now)
        context_payload = json.loads(Path(args.context).read_text(encoding="utf-8"))
        if not isinstance(context_payload, dict):
            raise ValueError("opportunity context must encode an object")
        context = _context(context_payload)
        metrics_provider = _metrics_provider(args.metrics_provider)
        candidate_provider = _candidate_provider(args.candidate_provider)
    except (
        ImportError,
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        parser.error(str(error))

    api_settings = ApiSettings.from_env()
    operational = OperationalSettings.from_env()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    security_master_path = _path(
        args.security_master_database,
        default=operational.security_master_database,
    )
    screening_path = _path(
        args.screening_database,
        default=Path(
            os.getenv(
                "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE",
                str(data_dir / "full_universe_screening.db"),
            )
        ).expanduser(),
    )
    slo_path = _path(args.slo_database, default=operational.operational_slo_database)
    journal_path = _path(args.journal_database, default=api_settings.journal_database)

    security_master_service = SecurityMasterIngestionService(
        SQLiteSecurityMasterStore(security_master_path),
        SQLiteSecurityMasterOperationalStore(security_master_path),
        activation_policy=SecurityMasterActivationPolicy(
            maximum_catalog_age_hours=operational.slo_provider_maximum_age_hours,
        ),
        certification_store=SQLiteProviderCertificationStore(security_master_path),
    )
    orchestrator = FullUniverseScreeningOrchestrator(
        security_master_service=security_master_service,
        metrics_provider=metrics_provider,
        candidate_provider=candidate_provider,
        screening_store=SQLiteFullUniverseScreeningStore(screening_path),
        slo_store=SQLiteOperationalSLOStore(slo_path),
        journal=SQLiteCIOJournal(journal_path),
    )
    request = FullUniverseScreeningRequest(
        identifier=args.cycle_id,
        scheduled_for=scheduled_for,
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
        started_at=started_at,
        partition_size=args.partition_size,
        maximum_partition_attempts=args.maximum_partition_attempts,
    )
    try:
        result = orchestrator.run(request, context)
    except FullUniverseScreeningError as error:
        print(
            json.dumps(
                {
                    "cycle_identifier": request.identifier,
                    "status": "failed",
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3
    print(
        json.dumps(
            {
                "status": "completed",
                "publication": result.publication.to_dict(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
