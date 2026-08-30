from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations import stage_isolated_evidence_pipeline as pipeline
from operations.historical_evidence_epoch_floor import (
    load_historical_evidence_epoch_floor,
    record_historical_evidence_epoch_floor,
)
from operations.persistent_historical_evidence import PersistentHistoricalEvidenceError
import run_stage_isolated_evidence_stage as stage_runtime


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-historical-floor-test",
    }


def _detail(snapshot: datetime, decision: datetime) -> str:
    return (
        "persistent historical evidence was refreshed after the decision epoch; "
        "asset_class=paper_listed; instrument_identity=SPY; "
        "provider_scope=alpaca_iex_1day; "
        f"decision_epoch={decision.isoformat()}; "
        f"earliest_available_requested_as_of={snapshot.isoformat()}"
    )


def test_retry_floor_is_observation_time_and_monotonic(tmp_path) -> None:
    values = _values(tmp_path)
    decision = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)
    snapshot = decision + timedelta(minutes=2)
    observed = decision + timedelta(minutes=5)

    first = record_historical_evidence_epoch_floor(
        _detail(snapshot, decision),
        values=values,
        observed_at=observed,
    )
    assert first == observed
    assert load_historical_evidence_epoch_floor(values) == observed

    older_observation = decision + timedelta(minutes=3)
    second = record_historical_evidence_epoch_floor(
        _detail(snapshot, decision),
        values=values,
        observed_at=older_observation,
    )
    assert second == observed
    assert load_historical_evidence_epoch_floor(values) == observed


def test_unrelated_historical_failure_does_not_create_retry_floor(tmp_path) -> None:
    values = _values(tmp_path)
    assert (
        record_historical_evidence_epoch_floor(
            "persistent historical evidence row integrity mismatch",
            values=values,
            observed_at=datetime(2026, 8, 30, 1, 5, tzinfo=timezone.utc),
        )
        is None
    )
    assert load_historical_evidence_epoch_floor(values) is None


def test_reference_stage_cannot_rebind_below_historical_retry_floor(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    decision = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)
    floor = decision + timedelta(minutes=5)
    record_historical_evidence_epoch_floor(
        _detail(decision + timedelta(minutes=2), decision),
        values=values,
        observed_at=floor,
    )

    from operations import component_qualified_evidence_maintenance as maintenance

    captured: dict[str, datetime] = {}
    monkeypatch.setattr(
        maintenance,
        "_resumable_evidence_cutoff",
        lambda _values, *, requested: decision,
    )

    def _bound(_values, *, preparation_cutoff):
        captured["cutoff"] = preparation_cutoff
        return SimpleNamespace(
            manifest_id="manifest-floor-test",
            path=tmp_path / "manifest.json",
        ), preparation_cutoff

    monkeypatch.setattr(maintenance, "_bound_or_prepare_reference_manifest", _bound)
    state = SimpleNamespace(evidence_as_of=decision)

    result = stage_runtime._stage_reference(values, state)

    assert captured["cutoff"] == floor
    assert result["evidence_as_of"] == floor


def test_paper_history_conflict_records_floor_before_stage_failure(
    tmp_path, monkeypatch
) -> None:
    values = _values(tmp_path)
    decision = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)
    snapshot = decision + timedelta(minutes=2)
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=decision,
    )
    for stage in (
        "reference",
        "public_live",
        "us_equity_discovery",
        "comprehensive_discovery",
    ):
        state = pipeline.begin_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
        )
        state = pipeline.complete_evidence_stage(
            values,
            pipeline_id=state.pipeline_id,
            stage=stage,
            reference_manifest_id=("manifest-1" if stage == "reference" else None),
            reference_manifest_path=(
                str(tmp_path / "manifest.json") if stage == "reference" else None
            ),
        )

    def _fail(_values, _state):
        raise PersistentHistoricalEvidenceError(_detail(snapshot, decision))

    monkeypatch.setitem(stage_runtime._STAGE_RUNNERS, "paper_evidence", _fail)

    assert stage_runtime.run_stage(
        "paper_evidence",
        pipeline_id=state.pipeline_id,
        values=values,
    ) == 2

    latest = pipeline.load_stage_isolated_evidence_state(values)
    assert latest is not None
    assert latest.state == "failed"
    assert latest.error_type == "PersistentHistoricalEvidenceError"
    retry_floor = load_historical_evidence_epoch_floor(values)
    assert retry_floor is not None
    assert retry_floor >= snapshot
    assert retry_floor > decision
