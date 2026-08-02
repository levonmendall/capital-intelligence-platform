"""Fail-closed resolution of the capability-certified active paper universe."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Mapping

from cio import RecommendationUniversePolicy
from governance.bounded_pilot_scope import BoundedPilotCapabilityAuthority
from governance.market_participation import CanonicalMarketParticipationAuthority
from opportunity import OpportunityEngine
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
    evaluated_at: datetime | None = None,
) -> FreePaperPilotUniverse:
    """Load the exact publication and apply current capability certifications.

    The persisted publication remains the complete candidate source. Bootstrap
    registry instruments and additional actively certified instruments may survive
    the ownership gate. An instrument missing from the publication cannot be
    introduced by the certification database.
    """

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
            universe,
            evaluated_at=evaluated_at,
        )
    detail = "; ".join(failures) or "no active-universe path was configured"
    raise ValueError(
        "the certified active paper universe is unavailable or does not match "
        f"the eligible-universe publication: {detail}"
    )


def build_active_recommendation_universe_policy(
    universe: FreePaperPilotUniverse,
) -> RecommendationUniversePolicy:
    """Build recommendation authority from the exact supplied active universe.

    The publication loader applies current market-participation and individual
    certification authority before returning a production universe. This factory must
    not independently reload and reinterpret that authority: doing so can silently
    remove a newly certified publication member when the process-local authority store
    differs from the publication timestamp. The exact supplied universe is therefore
    the sole instrument-membership boundary for committee and CIO qualification.
    Paper execution independently rechecks current capability authority and remains
    fail-closed.
    """

    if not str(getattr(universe, "identifier", "")).strip() or not tuple(
        getattr(universe, "instruments", ())
    ):
        raise TypeError(
            "universe must expose a non-empty identifier and instrument collection"
        )
    authority = BoundedPilotCapabilityAuthority.from_universe(universe)
    # The supplied active universe has already crossed the market-participation gate.
    # Disable only the redundant process-local reload while retaining production
    # identity, structure, exposure, venue, country, and leverage validation.
    authority.require_market_participation_authority = False
    return RecommendationUniversePolicy(asset_class_authority=authority)


def build_active_opportunity_engine(
    universe: FreePaperPilotUniverse,
    *,
    template: OpportunityEngine | None = None,
) -> OpportunityEngine:
    """Build an opportunity engine with mandatory active-universe capability authority."""

    if template is not None and not isinstance(template, OpportunityEngine):
        raise TypeError("template must be an OpportunityEngine or None")
    return OpportunityEngine(
        universe_policy=build_active_recommendation_universe_policy(universe),
        qualification_policy=None if template is None else template.policy,
        robustness_policy=(
            None if template is None else template.robust_assessor.policy
        ),
        policy_matrix=None if template is None else template.policy_matrix,
    )


__all__ = [
    "build_active_opportunity_engine",
    "build_active_recommendation_universe_policy",
    "load_active_paper_universe_for_publication",
]
