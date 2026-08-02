"""Fail-closed resolution of the registry-certified active paper universe."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from governance.market_participation import CanonicalMarketParticipationAuthority
from operations.free_paper_pilot import (
    FreePaperPilotUniverse,
    _free_paper_pilot_universe_from_payload,
    active_paper_universe_path,
)


def _candidate_paths(path: str | Path | None) -> tuple[Path, ...]:
    if path is not None:
        return (Path(path).expanduser(),)
    values = [active_paper_universe_path()]
    portfolio_database = os.getenv(
        "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", ""
    ).strip()
    if portfolio_database:
        values.append(
            Path(portfolio_database).expanduser().with_name("active-paper-universe.json")
        )
    return tuple(dict.fromkeys(values))


def load_active_paper_universe_for_publication(
    publication_identifier: str,
    *,
    path: str | Path | None = None,
) -> FreePaperPilotUniverse:
    """Load the exact publication and apply the canonical market registry."""

    resolved_identifier = str(publication_identifier).strip()
    if not resolved_identifier:
        raise ValueError("publication_identifier cannot be empty")
    failures: list[str] = []
    for source in _candidate_paths(path):
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{source}: {type(error).__name__}")
            continue
        if not isinstance(payload, Mapping):
            failures.append(f"{source}: payload is not a JSON object")
            continue
        persisted_identifier = str(
            payload.get("eligible_universe_publication_identifier", "")
        ).strip()
        if persisted_identifier != resolved_identifier:
            failures.append(f"{source}: publication identifier mismatch")
            continue
        universe_payload = payload.get("universe")
        if not isinstance(universe_payload, Mapping):
            failures.append(f"{source}: universe payload is unavailable")
            continue
        universe = _free_paper_pilot_universe_from_payload(universe_payload)
        return CanonicalMarketParticipationAuthority.load().decision_authority_universe(
            universe
        )
    detail = "; ".join(failures) or "no active-universe path was configured"
    raise ValueError(
        "the certified active paper universe is unavailable or does not match "
        f"the eligible-universe publication: {detail}"
    )


__all__ = ["load_active_paper_universe_for_publication"]
