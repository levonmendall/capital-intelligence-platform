"""Assemble credential-safe technical provider certification without legal approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


def _load(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"report {path!r} must be a JSON object")
    return payload


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _credential_ready(report: Mapping[str, Any]) -> bool:
    configured = int(report.get("configured_provider_count") or 0)
    passed = int(report.get("passed_provider_count") or 0)
    blockers = report.get("blockers") or []
    return configured > 0 and configured == passed and not blockers


def _runtime_ready(report: Mapping[str, Any]) -> bool:
    providers = report.get("providers")
    if not isinstance(providers, list):
        return False
    configured = [
        item
        for item in providers
        if isinstance(item, Mapping)
        and item.get("provider")
        in {
            "alpaca_paper",
            "fred",
            "databento",
            "eodhd",
            "openfigi",
            "alpha_vantage",
            "twelve_data",
            "coinbase_exchange",
            "kraken_spot",
        }
    ]
    return bool(configured) and all(bool(item.get("runtime_ready")) for item in configured)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-report", required=True)
    parser.add_argument("--runtime-report", required=True)
    parser.add_argument("--databento-report", required=True)
    parser.add_argument("--eodhd-binding-manifest")
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-technical-ready", action="store_true")
    return parser


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must include a UTC offset")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        credential = _load(args.credential_report)
        runtime = _load(args.runtime_report)
        databento = _load(args.databento_report)
        eodhd = _load(args.eodhd_binding_manifest) if args.eodhd_binding_manifest else None
        credential_ready = _credential_ready(credential)
        runtime_ready = _runtime_ready(runtime)
        databento_ready = (
            bool(databento.get("configured"))
            and int(databento.get("dataset_count") or 0) > 0
            and int(databento.get("available_binding_count") or 0) > 0
            and databento.get("state") in {"available", "partial"}
        )
        eodhd_ready = eodhd is None or bool(eodhd.get("bindings"))
        technical_ready = all(
            (credential_ready, runtime_ready, databento_ready, eodhd_ready)
        )
        runtime_providers = runtime.get("providers")
        approval_inputs_present = False
        certification_inputs_present = False
        if isinstance(runtime_providers, list):
            approval_inputs_present = any(
                bool(item.get("license_approval_input_present"))
                for item in runtime_providers
                if isinstance(item, Mapping)
            )
            certification_inputs_present = any(
                bool(item.get("certification_input_present"))
                for item in runtime_providers
                if isinstance(item, Mapping)
            )
        blockers: list[str] = []
        if not credential_ready:
            blockers.append("credential_validation_incomplete")
        if not runtime_ready:
            blockers.append("runtime_credentials_or_bindings_incomplete")
        if not databento_ready:
            blockers.append("databento_catalog_or_binding_incomplete")
        if not eodhd_ready:
            blockers.append("eodhd_binding_manifest_empty")
        if not approval_inputs_present:
            blockers.append("human_license_approval_inputs_missing")
        if not certification_inputs_present:
            blockers.append("provider_certification_inputs_missing")
        source_reports = {
            "credential_report_sha256": _hash(credential),
            "runtime_report_sha256": _hash(runtime),
            "databento_report_sha256": _hash(databento),
            "eodhd_binding_manifest_sha256": None if eodhd is None else _hash(eodhd),
        }
        payload: dict[str, Any] = {
            "schema_version": "provider-technical-certification.v1",
            "evaluated_at": _timestamp(args.as_of).isoformat(),
            "state": (
                "technical_ready_legal_pending"
                if technical_ready
                else "technical_blocked"
            ),
            "technical_ready": technical_ready,
            "credential_validation_ready": credential_ready,
            "runtime_integration_ready": runtime_ready,
            "databento_native_ingestion_ready": databento_ready,
            "eodhd_binding_manifest_ready": eodhd_ready,
            "human_license_approval_inputs_present": approval_inputs_present,
            "provider_certification_inputs_present": certification_inputs_present,
            "provider_activation_granted": False,
            "asset_class_paper_approval_granted": False,
            "real_money_authorized": False,
            "blockers": blockers,
            "source_reports": source_reports,
            "secret_values_disclosed": False,
        }
        payload["report_sha256"] = _hash(payload)
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.require_technical_ready and not technical_ready:
            return 3
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "provider-technical-certification.v1",
                    "state": "blocked",
                    "error": str(error),
                    "provider_activation_granted": False,
                    "asset_class_paper_approval_granted": False,
                    "real_money_authorized": False,
                    "secret_values_disclosed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
