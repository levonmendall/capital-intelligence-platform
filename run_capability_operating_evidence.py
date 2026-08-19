"""Refresh the independent capability-scoped operating evidence snapshot once."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from operations.capability_operating_evidence import (
    CapabilityOperatingEvidenceError,
    refresh_capability_operating_evidence,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.parse_args(argv)
    try:
        evidence = refresh_capability_operating_evidence()
    except (CapabilityOperatingEvidenceError, OSError, TypeError, ValueError, RuntimeError) as error:
        # Provider exceptions can contain request URLs or credential-adjacent material.
        # The bounded parent needs only a stable failure type; detailed provider evidence
        # remains in provider-owned diagnostics rather than the Render bootstrap log.
        print(
            json.dumps(
                {
                    "event": "capability_operating_evidence_failed",
                    "error_type": type(error).__name__,
                    "credential_safe": True,
                    "comprehensive_discovery_required": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2

    print(
        json.dumps(
            {
                "event": "capability_operating_evidence_completed",
                "as_of": evidence.as_of.isoformat(),
                "completed_at": evidence.completed_at.isoformat(),
                "snapshot_id": evidence.snapshot_id,
                "instrument_count": len(evidence.universe.instruments),
                "held_symbol_count": len(evidence.held_symbols),
                "holding_only_count": len(evidence.holding_only_symbols),
                "comprehensive_discovery_required": False,
                "investment_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
