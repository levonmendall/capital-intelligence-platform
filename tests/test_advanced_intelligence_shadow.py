from datetime import UTC, datetime

from intelligence.advanced_shadow import (
    AdvancedEngine,
    AdvancedIntelligenceShadowCoordinator,
    SQLiteAdvancedShadowStore,
    ShadowEngineState,
)


AS_OF = datetime(2026, 8, 3, tzinfo=UTC)


def test_shadow_cycle_is_append_only_and_excluded_from_authority(tmp_path):
    snapshot = AdvancedIntelligenceShadowCoordinator().observe_cycle(
        cycle_identifier="cycle:1",
        as_of=AS_OF,
        code_version="commit:abc",
        candidate_count=2,
        specialist_context_count=2,
        decision_count=1,
        alternative_count=3,
        posture_identifier="posture:1",
    )
    assert snapshot.excluded_from_cio_calculations
    assert not snapshot.authorizes_portfolio_change
    institutional = next(
        item
        for item in snapshot.records
        if item.engine is AdvancedEngine.INSTITUTIONAL_DATA
    )
    assert (
        institutional.state
        is ShadowEngineState.DISABLED_PENDING_CERTIFICATION
    )
    store = SQLiteAdvancedShadowStore(tmp_path / "shadow.sqlite")
    store.append(snapshot)
    store.verify()
