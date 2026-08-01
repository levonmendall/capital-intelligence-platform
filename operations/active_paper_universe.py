"""Fail-closed resolution of the exact certified active paper universe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from operations.free_paper_pilot import (
    FreePaperPilotUniverse,
    _free_paper_pilot_universe_from_payload,
    active_paper_universe_path,
)


def load_active_paper_universe_for_publication(
    publication_identifier: str,
    *,
    path: str | Path | None = None,
) -> FreePaperPilotUniverse:
    """Load only the dynamic universe bound to one certified publication.

    There is deliberately no static-universe fallback. A missing, malformed, or
    mismatched active publication is an authority failure and must stop the CIO
    rather than silently excluding dynamically discovered instruments.
    """

    resolved_identifier = str(publication_identifier).strip()
    if not resolved_identifier:
        raise ValueError("publication_identifier cannot be empty")
    source = (
        Path(path).expanduser()
        if path is not None
        else active_paper_universe_path()
    )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            "the certified active paper universe is unavailable"
        ) from error
    if not isinstance(payload, Mapping):
        raise ValueError("the active paper universe must be a JSON object")
    persisted_identifier = str(
        payload.get("eligible_universe_publication_identifier", "")
    ).strip()
    if persisted_identifier != resolved_identifier:
        raise ValueError(
            "the active paper universe does not match the certified eligible-universe publication"
        )
    universe_payload = payload.get("universe")
    if not isinstance(universe_payload, Mapping):
        raise ValueError("the active paper universe payload is unavailable")
    return _free_paper_pilot_universe_from_payload(universe_payload)


__all__ = ["load_active_paper_universe_for_publication"]
