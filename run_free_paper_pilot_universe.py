"""Publish a certified free-pilot eligible universe for one exact CIO cycle time."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from governance.eligible_universe import (
    CertifiedEligibleUniversePublication,
    EligibleUniverseCertificationState,
    SQLiteCertifiedEligibleUniverseStore,
)
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    assess_free_paper_pilot_readiness,
    default_alpaca_client,
    load_free_paper_pilot_universe,
    write_pilot_profiles,
)


def _decision_at(value: str | None, *, now: datetime) -> datetime:
    if value is None:
        return now + timedelta(minutes=2)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--decision-at must include a UTC offset")
    if parsed < now:
        raise ValueError("--decision-at cannot be earlier than publication time")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--decision-at")
    parser.add_argument(
        "--eligible-universe-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ELIGIBLE_UNIVERSE_DATABASE",
            str(data_dir / "eligible_universe.db"),
        ),
    )
    parser.add_argument(
        "--profiles-output",
        default=str(data_dir / "free_paper_pilot_profiles.json"),
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        environment = (
            os.getenv("CAPITAL_INTELLIGENCE_ENVIRONMENT")
            or os.getenv("CAPITAL_INTELLIGENCE_DEPLOYMENT_ENVIRONMENT")
            or "development"
        ).strip().lower()
        if environment != "development":
            raise ValueError(
                "free pilot universe publication is development-only"
            )
        now = datetime.now(timezone.utc)
        decision_at = _decision_at(args.decision_at, now=now)
        universe = load_free_paper_pilot_universe(args.universe)
        readiness = assess_free_paper_pilot_readiness(
            universe=universe,
            client=default_alpaca_client(),
            evaluated_at=now,
        )
        if not readiness.configuration_ready:
            raise ValueError(
                "free pilot configuration is not ready: "
                + "; ".join(readiness.blockers)
            )
        readiness_payload = readiness.to_dict()
        fingerprint = str(readiness_payload["fingerprint"])
        publication = CertifiedEligibleUniversePublication(
            identifier=(
                f"eligible-universe:free-paper-pilot:{decision_at.isoformat()}"
            ),
            published_at=now,
            as_of=decision_at,
            knowledge_cutoff=now,
            security_master_catalog_identifier=universe.identifier,
            security_master_snapshot_identifier=(
                f"alpaca-paper-asset-snapshot:{fingerprint}"
            ),
            policy_version="free-paper-pilot-eligibility.v1",
            certification_identifier=(
                f"free-paper-pilot-certification:{fingerprint}"
            ),
            certification_state=EligibleUniverseCertificationState.APPROVED,
            certification_expires_at=decision_at + timedelta(days=1),
            eligible_instrument_identifiers=tuple(
                item.instrument_identifier for item in universe.instruments
            ),
            source_versions=(
                ("alpaca-paper-assets", "v2"),
                ("alpaca-iex-latest-quotes", "v2"),
                ("free-paper-pilot-universe", universe.schema_version),
            ),
            model_versions=(
                ("eligibility-policy", "free-paper-pilot-eligibility.v1"),
                ("paper-execution", "multi-asset-paper-execution.v2"),
            ),
        )
        store = SQLiteCertifiedEligibleUniverseStore(
            args.eligible_universe_database
        )
        sequence = store.append(publication)
        profiles_path = write_pilot_profiles(universe, args.profiles_output)
        payload = {
            "status": "published",
            "sequence": sequence,
            "decision_at": decision_at.isoformat(),
            "publication": publication.to_dict(),
            "profiles_path": str(profiles_path),
            "configuration_readiness": readiness_payload,
            "next_step": (
                "Run the canonical CIO cycle with the exact decision_at timestamp, "
                "approve its exact construction, then execute run_free_paper_pilot.py."
            ),
            "real_money_authorized": False,
        }
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
