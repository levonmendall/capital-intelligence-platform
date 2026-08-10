from datetime import datetime, timezone

from cio.models import CandidateAssetClass
from intelligence.global_macro_overlay import (
    GlobalMacroStateEngine,
    MacroDimension,
    MacroObservation,
)


def test_global_macro_overlay_is_shadow_by_default() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    observations = (
        MacroObservation("growth", now, "GLOBAL", MacroDimension.GROWTH, 0.8, 0.9, ("g",)),
        MacroObservation("credit", now, "GLOBAL", MacroDimension.CREDIT, -0.6, 0.8, ("c",)),
    )
    engine = GlobalMacroStateEngine()
    state = engine.aggregate(observations, as_of=now)
    signal = engine.candidate_signal(
        candidate_identifier="candidate:1",
        asset_class=CandidateAssetClass.US_EQUITY,
        state=state,
    )
    assert signal is not None
    assert signal.expected_return_impact == 0.0
    assert "macro" in signal.channels
    assert set(signal.evidence_identifiers) == {"g", "c"}
