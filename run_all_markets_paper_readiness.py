"""Assess repository-internal and external activation readiness for all markets."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from governance import (
    SQLiteAssetClassApprovalStore,
    SQLiteDecisionInformationActivationStore,
    load_all_market_provider_bundle,
    load_data_readiness_manifest,
    load_maximum_decision_information_manifest,
)
from governance.provider_activation import SQLiteProviderActivationStore
from data.derivative_market import DerivativeDataCertificationReport
from operations.paper_market_readiness import (
    assess_universal_paper_market_readiness,
)
from providers.free_derivative_risk import preflight_free_derivative_risk_resources


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must include a UTC offset")
    return parsed


def _env_file(path: str | None) -> dict[str, str]:
    values = dict(os.environ)
    if path is None:
        return values
    for line_number, raw in enumerate(
        Path(path).expanduser().read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"invalid environment assignment on line {line_number}")
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="config/all_markets_data_readiness.json"
    )
    parser.add_argument(
        "--information-manifest",
        default="config/maximum_decision_information_scope.json",
    )
    parser.add_argument(
        "--provider-bundle",
        default="config/all_market_provider_bundle.json",
    )
    parser.add_argument("--skip-provider-bundle", action="store_true")
    parser.add_argument(
        "--provider-activation-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PROVIDER_ACTIVATION_DATABASE",
            "database/provider-activations.db",
        ),
    )
    parser.add_argument(
        "--information-activation-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_ACTIVATION_DATABASE",
            "database/decision-information-activations.db",
        ),
    )
    parser.add_argument(
        "--asset-class-governance-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ASSET_CLASS_GOVERNANCE_DATABASE",
            "database/asset-class-governance.db",
        ),
    )
    parser.add_argument("--provider-binding", action="append", default=[])
    parser.add_argument(
        "--derivative-data-certification",
        help=(
            "Canonical derivative-data-certification-report.v1 JSON evidence. "
            "Defaults to CAPITAL_INTELLIGENCE_DERIVATIVE_DATA_CERTIFICATION."
        ),
    )
    parser.add_argument("--env-file")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--output")
    parser.add_argument("--require-internal-ready", action="store_true")
    parser.add_argument("--require-paper-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        environment = _env_file(args.env_file)
        evaluated_at = _timestamp(args.evaluated_at)
        derivative_preflight = preflight_free_derivative_risk_resources(
            as_of=evaluated_at,
            environment=environment,
        )
        canonical_binding_variables = (
            "CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATASET_BINDING",
            "CAPITAL_INTELLIGENCE_UNIVERSE_METRICS_DATASET_BINDING",
            "CAPITAL_INTELLIGENCE_CANDIDATE_SCREENING_DATASET_BINDING",
            "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_DATASET_BINDING",
        )
        provider_binding_paths = list(args.provider_binding)
        for variable in canonical_binding_variables:
            value = str(environment.get(variable, "")).strip()
            if value and value not in provider_binding_paths:
                provider_binding_paths.append(value)
        derivative_path = (
            args.derivative_data_certification
            or str(
                environment.get(
                    "CAPITAL_INTELLIGENCE_DERIVATIVE_DATA_CERTIFICATION", ""
                )
            ).strip()
            or None
        )
        report = assess_universal_paper_market_readiness(
            manifest=load_data_readiness_manifest(args.manifest),
            information_manifest=load_maximum_decision_information_manifest(
                args.information_manifest
            ),
            evaluated_at=evaluated_at,
            environment=environment,
            provider_activation_store=SQLiteProviderActivationStore(
                args.provider_activation_database
            ),
            decision_information_activation_store=(
                SQLiteDecisionInformationActivationStore(
                    args.information_activation_database
                )
            ),
            asset_class_approval_store=SQLiteAssetClassApprovalStore(
                args.asset_class_governance_database
            ),
            provider_binding_paths=tuple(provider_binding_paths),
            provider_bundle=(
                None
                if args.skip_provider_bundle
                else load_all_market_provider_bundle(args.provider_bundle)
            ),
            derivative_data_certification=(
                None
                if derivative_path is None
                else DerivativeDataCertificationReport.from_dict(
                    json.loads(
                        Path(derivative_path)
                        .expanduser()
                        .read_text(encoding="utf-8")
                    )
                )
            ),
        )
        payload = report.to_dict()
        payload["free_derivative_risk_preflight"] = derivative_preflight.to_dict()
        resource_ready = not derivative_preflight.blockers
        if derivative_preflight.blockers:
            payload["paper_ready"] = False
            payload["free_derivative_risk_blockers"] = list(
                derivative_preflight.blockers
            )
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.require_paper_ready:
            return 0 if report.paper_ready and resource_ready else 3
        if args.require_internal_ready:
            return 0 if report.internal_ready and resource_ready else 3
        if report.paper_ready and resource_ready:
            return 0
        if report.internal_ready and resource_ready:
            return 2
        return 3
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(
            json.dumps(
                {
                    "error": str(error),
                    "internal_ready": False,
                    "paper_ready": False,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
