from __future__ import annotations

from types import SimpleNamespace

from operations.capability_operating_evidence import CapabilityOperatingEvidenceError
import run_bounded_capability_operating_evidence as subject


class _Lease:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


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


def test_release_priority_rechecks_snapshot_after_waiting_owner_finishes(
    monkeypatch,
    capsys,
) -> None:
    evidence = SimpleNamespace(snapshot_id="snapshot-background")
    snapshots = iter((None, None, evidence))
    priority = _Lease()
    probe = _Lease()
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: next(snapshots),
    )
    monkeypatch.setattr(
        subject,
        "acquire_memory_lane_priority",
        lambda *_args, **_kwargs: priority,
    )
    monkeypatch.setattr(
        subject,
        "acquire_memory_lane",
        lambda *_args, **_kwargs: probe,
    )

    def unexpected_refresh(*_args, **_kwargs):
        raise AssertionError("background snapshot completion must prevent a duplicate build")

    monkeypatch.setattr(subject, "_run_isolated_once", unexpected_refresh)

    assert subject.run_operating_once({}) == 0
    assert priority.released is True
    assert probe.released is True

    output = capsys.readouterr().out
    assert "capability_operating_evidence_priority_acquired" in output
    assert "capability_operating_evidence_reused" in output
    assert '"after_lane_busy": true' in output


def test_priority_wait_accepts_snapshot_completed_while_heavy_lane_is_busy(
    monkeypatch,
    capsys,
) -> None:
    evidence = SimpleNamespace(snapshot_id="snapshot-background")
    snapshots = iter((None, None, evidence))
    priority = _Lease()
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: next(snapshots),
    )
    monkeypatch.setattr(
        subject,
        "acquire_memory_lane_priority",
        lambda *_args, **_kwargs: priority,
    )
    monkeypatch.setattr(
        subject,
        "acquire_memory_lane",
        lambda *_args, **_kwargs: None,
    )

    def unexpected_refresh(*_args, **_kwargs):
        raise AssertionError("busy owner completion must be reused before a duplicate build")

    monkeypatch.setattr(subject, "_run_isolated_once", unexpected_refresh)

    assert subject.run_operating_once({}) == 0
    assert priority.released is True

    output = capsys.readouterr().out
    assert "capability_operating_evidence_reused" in output
    assert '"after_lane_busy": true' in output


def test_missing_or_stale_snapshot_runs_refresh_under_release_priority(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "_load_fresh_operating_evidence",
        lambda _values: None,
    )
    priority = _Lease()
    probe = _Lease()
    monkeypatch.setattr(
        subject,
        "acquire_memory_lane_priority",
        lambda *_args, **_kwargs: priority,
    )
    monkeypatch.setattr(
        subject,
        "acquire_memory_lane",
        lambda *_args, **_kwargs: probe,
    )
    monkeypatch.setattr(subject, "_one_shot_budget_seconds", lambda _values: 1.0)
    monotonic = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr(subject.time, "monotonic", lambda: next(monotonic))
    observed = {}

    def bounded_refresh(
        spec,
        *,
        values,
        timeout_seconds,
        lane_wait_seconds,
    ):
        observed["spec"] = spec
        observed["values"] = values
        observed["timeout_seconds"] = timeout_seconds
        observed["lane_wait_seconds"] = lane_wait_seconds
        return 126

    monkeypatch.setattr(subject, "_run_isolated_once", bounded_refresh)

    values = {
        "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MEMORY_LANE_WAIT_SECONDS": "17",
    }
    assert subject.run_operating_once(values) == 126
    assert observed["spec"] is subject._SPEC
    assert observed["values"][subject.MEMORY_LANE_PRIORITY_BYPASS_ENV] == "true"
    assert observed["lane_wait_seconds"] == 0.0
    assert observed["timeout_seconds"] == 1.0
    assert priority.released is True
    assert probe.released is True


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
