from datetime import datetime, timezone

from application.production_context import _market_from_dict, _market_to_dict
from committee.specialists import MarketSpecialistContext


AS_OF = datetime(2026, 8, 9, 23, 45, tzinfo=timezone.utc)


def _market():
    return MarketSpecialistContext(
        as_of=AS_OF,
        market_regime="global_leadership",
        expected_return_impact=0.02,
        confidence=0.75,
        trend=0.7,
        momentum=0.6,
        breadth=0.5,
        liquidity=0.9,
        positioning=0.1,
        evidence=("Global opportunity radar confirms broad leadership.",),
        risks=("Leadership can reverse.",),
        entry_conditions=("Evidence remains current.",),
        evidence_identifiers=(
            "market:global-radar:20260809",
            "provider-dataset:reviewed-exposure-graph:abc123",
        ),
    )


def test_market_context_round_trip_preserves_evidence_identifiers():
    original = _market()
    payload = _market_to_dict(original)
    assert payload["evidence_identifiers"] == list(original.evidence_identifiers)
    restored = _market_from_dict(payload)
    assert restored == original


def test_market_context_old_snapshot_without_identifiers_remains_readable():
    payload = _market_to_dict(_market())
    payload.pop("evidence_identifiers")
    restored = _market_from_dict(payload)
    assert restored.evidence_identifiers == ()
