from __future__ import annotations

from types import SimpleNamespace

from operations.capability_operating_evidence import CapabilityOperatingEvidenceError
import run_bounded_capability_operating_evidence as subject


def test_release_once_reuses_fresh_snapshot_without_competing_for_memory_lane(
    monkeypatch,
    capsys,
) -> None:
    evidence = SimpleNamespace(snapshot_id="snapshot-current")
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: evidence,
    )

    def unexpected_refresh(*_args, **_kwargs):
        raise AssertionError("fresh release evidence must not launch a duplicate heavy child")

    monkeypatch.setattr(subject, "_run_isolated_once", unexpected_refresh)

    assert subject.run_operating_once({}) == 0

    output = capsys.readouterr().out
    assert "capability_operating_evidence_reused" in output
    assert '"after_lane_busy": false' in output
    assert '"decision_authority": false' in output
    assert '"execution_authority": false' in output
    assert '"paper_only": true' in output
    assert '"real_money_authorized": false' in output


def test_lane_busy_accepts_snapshot_completed_during_bounded_wait(
    monkeypatch,
    capsys,
) -> None:
    evidence = SimpleNamespace(snapshot_id="snapshot-background")
    snapshots = iter((None, evidence))
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: next(snapshots),
    )
    monkeypatch.setattr(
        subject,
        "_run_isolated_once",
        lambda *_args, **_kwargs: 126,
    )

    assert subject.run_operating_once({}) == 0

    output = capsys.readouterr().out
    assert "capability_operating_evidence_reused" in output
    assert '"after_lane_busy": true' in output


def test_missing_or_stale_snapshot_falls_through_to_bounded_refresh(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: None,
    )
    observed = {}

    def bounded_refresh(spec, *, values, lane_wait_seconds):
        observed["spec"] = spec
        observed["values"] = values
        observed["lane_wait_seconds"] = lane_wait_seconds
        return 126

    monkeypatch.setattr(subject, "_run_isolated_once", bounded_refresh)

    values = {
        "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MEMORY_LANE_WAIT_SECONDS": "17",
    }
    assert subject.run_operating_once(values) == 126
    assert observed["spec"] is subject._SPEC
    assert observed["values"] == values
    assert observed["lane_wait_seconds"] == 17.0


def test_canonical_loader_is_the_only_reuse_gate(monkeypatch) -> None:
    from operations import capability_operating_evidence as operating

    observed = {}

    def unavailable(*, cutoff, values):
        observed["cutoff"] = cutoff
        observed["values"] = values
        raise CapabilityOperatingEvidenceError("stale")

    monkeypatch.setattr(operating, "load_capability_operating_evidence", unavailable)
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/evidence"}

    assert subject._load_fresh_operating_evidence(values) is None
    assert observed["values"] is values
    assert observed["cutoff"].tzinfo is not None


def test_background_loop_keeps_existing_refresh_cadence(monkeypatch) -> None:
    observed = {}

    def run_loop(spec, *, values, initial_delay_seconds):
        observed["spec"] = spec
        observed["values"] = values
        observed["initial_delay_seconds"] = initial_delay_seconds
        return 7

    monkeypatch.setattr(subject, "run_loop", run_loop)
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: (_ for _ in ()).throw(
            AssertionError("background loop must not use release one-shot reuse")
        ),
    )

    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/evidence"}
    assert subject.run_operating_loop(values=values, initial_delay_seconds=9.0) == 7
    assert observed["spec"] is subject._SPEC
    assert observed["values"] is values
    assert observed["initial_delay_seconds"] == 9.0
