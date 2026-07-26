"""Run and persist a vendor-neutral security-master certification suite."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from data import (
    ProviderCertificationDecision,
    ProviderCertificationHarness,
    SQLiteProviderCertificationStore,
    manifest_from_payload,
    report_to_payload,
    scenario_from_payload,
)


def _database_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATABASE",
            str(data_dir / "security_master.db"),
        )
    ).expanduser()


def _json(path: str) -> object:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _provider(factory_path: str):
    if ":" not in factory_path:
        raise ValueError("provider factory must use module:function syntax")
    module_name, attribute_name = factory_path.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attribute_name)
    provider = factory()
    if not hasattr(provider, "fetch_security_master_delivery"):
        raise TypeError("provider factory did not return a security-master provider")
    return provider


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Certify a security-master provider against commercial capability "
            "claims and deterministic point-in-time acceptance scenarios."
        )
    )
    parser.add_argument("--provider-factory", required=True, help="Python module:function provider factory.")
    parser.add_argument("--manifest", required=True, help="Provider capability manifest JSON.")
    parser.add_argument("--suite", required=True, help="Certification scenario list JSON.")
    parser.add_argument("--database", help="Override the certification registry database path.")
    parser.add_argument("--identifier", help="Immutable certification report identifier.")
    parser.add_argument("--certified-at", help="Timezone-aware ISO-8601 certification timestamp.")
    args = parser.parse_args(argv)

    now = (
        datetime.now(timezone.utc)
        if args.certified_at is None
        else datetime.fromisoformat(args.certified_at.replace("Z", "+00:00"))
    )
    if now.tzinfo is None or now.utcoffset() is None:
        parser.error("--certified-at must include a UTC offset")
    manifest_payload = _json(args.manifest)
    suite_payload = _json(args.suite)
    if not isinstance(manifest_payload, dict):
        parser.error("manifest JSON must be an object")
    if not isinstance(suite_payload, list):
        parser.error("suite JSON must be a list")
    try:
        manifest = manifest_from_payload(manifest_payload)
        scenarios = tuple(scenario_from_payload(item) for item in suite_payload)
        provider = _provider(args.provider_factory)
        report = ProviderCertificationHarness().certify(
            provider,
            manifest,
            scenarios,
            identifier=(
                args.identifier
                or f"provider-certification:{manifest.provider.lower()}:{now.isoformat()}"
            ),
            certified_at=now,
        )
        store = SQLiteProviderCertificationStore(_database_path(args.database))
        event = store.append(report)
        store.verify_integrity()
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(json.dumps({"error": str(error)}, indent=2))
        return 4

    payload = report_to_payload(report)
    payload["registry_sequence"] = event.sequence
    payload["content_hash"] = event.content_hash
    print(json.dumps(payload, indent=2))
    if report.decision is ProviderCertificationDecision.APPROVED:
        return 0
    if report.decision is ProviderCertificationDecision.CONDITIONALLY_APPROVED:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
