from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from operations.free_paper_pilot import load_free_paper_pilot_universe
from operations.paper_evidence_snapshot import (
    PaperEvidenceSnapshotError,
    load_paper_evidence_snapshot,
    publish_paper_evidence_snapshot,
)
from providers.fred import FREDObservation


def _payload(symbol: str, as_of: datetime):
    return {
        "bars": {
            symbol: [
                {
                    "t": (as_of - timedelta(days=2)).isoformat(),
                    "c": 100.0,
                    "v": 1000.0,
                },
                {
                    "t": (as_of - timedelta(days=1)).isoformat(),
                    "c": 101.0,
                    "v": 1100.0,
                },
            ]
        },
        "quotes": {
            symbol: {
                "bp": 100.9,
                "ap": 101.1,
                "t": as_of.isoformat(),
            }
        },
        "macro": {
            "DGS10": FREDObservation(date="2026-08-14", value=4.1),
            "T10Y2Y": FREDObservation(date="2026-08-14", value=0.5),
            "VIXCLS": FREDObservation(date="2026-08-14", value=16.0),
            "DFF": FREDObservation(date="2026-08-14", value=3.75),
        },
        "company_facts": {},
        "provider_clock": {
            "timestamp": as_of.isoformat(),
            "is_open": True,
            "source": "fixture",
        },
        "_direct_market_errors": {},
        "_scheduled_closed_symbols": (),
    }


def test_snapshot_round_trip_uses_persistent_history_and_content_addressed_blobs(
    tmp_path,
) -> None:
    as_of = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)
    universe = load_free_paper_pilot_universe()
    symbol = universe.instruments[0].symbol
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}

    snapshot = publish_paper_evidence_snapshot(
        _payload(symbol, as_of),
        universe=universe,
        evidence_as_of=as_of,
        values=values,
        requested_history_days=3650,
    )
    restored = load_paper_evidence_snapshot(
        evidence_as_of=as_of,
        universe=universe,
        values=values,
    )

    assert restored.snapshot_id == snapshot.snapshot_id
    assert restored.evidence_as_of == as_of
    assert len(restored.payload["bars"][symbol]) == 2
    assert restored.payload["quotes"][symbol]["bp"] == 100.9
    assert restored.payload["macro"]["DGS10"].value == 4.1
    assert restored.payload["_paper_evidence_snapshot_id"] == snapshot.snapshot_id


def test_snapshot_identity_is_release_independent(tmp_path) -> None:
    as_of = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)
    universe = load_free_paper_pilot_universe()
    symbol = universe.instruments[0].symbol
    base = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}

    first = publish_paper_evidence_snapshot(
        _payload(symbol, as_of),
        universe=universe,
        evidence_as_of=as_of,
        values={**base, "CAPITAL_INTELLIGENCE_RELEASE": "release-a"},
        requested_history_days=3650,
    )
    second = publish_paper_evidence_snapshot(
        _payload(symbol, as_of),
        universe=universe,
        evidence_as_of=as_of,
        values={**base, "CAPITAL_INTELLIGENCE_RELEASE": "release-b"},
        requested_history_days=3650,
    )

    assert first.snapshot_id == second.snapshot_id


def test_changed_instrument_contract_fails_closed(tmp_path) -> None:
    as_of = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)
    universe = load_free_paper_pilot_universe()
    symbol = universe.instruments[0].symbol
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    publish_paper_evidence_snapshot(
        _payload(symbol, as_of),
        universe=universe,
        evidence_as_of=as_of,
        values=values,
        requested_history_days=3650,
    )
    changed = replace(
        universe,
        maximum_quote_age_minutes=universe.maximum_quote_age_minutes + 1,
    )

    with pytest.raises(PaperEvidenceSnapshotError, match="universe scope"):
        load_paper_evidence_snapshot(
            evidence_as_of=as_of,
            universe=changed,
            values=values,
        )
