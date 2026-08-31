from __future__ import annotations

from datetime import datetime, timezone

from operations import epoch_scoped_provider_acquisition as acquisition
from operations import resilient_comprehensive_discovery_prewarm as resilient


EPOCH = datetime(2026, 8, 31, 17, 24, tzinfo=timezone.utc)


def test_failed_early_provider_pass_retries_without_extending_budget(monkeypatch) -> None:
    canonical_budget = acquisition._fanout_budget_seconds
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *args, **kwargs: 300.0)
    calls = []
    observed_budgets = []

    def fake_original(request_path, *, values, decision_epoch):
        del request_path
        calls.append(dict(values))
        observed_budgets.append(
            acquisition._fanout_budget_seconds(decision_epoch, values)
        )
        if len(calls) == 1:
            return {"failed": 1, "provider_skipped_budget": 0, "completed": 12}
        return {"failed": 0, "provider_skipped_budget": 0, "completed": 13}

    result = resilient._run_resilient_fanout(
        "request.json",
        values={"RENDER": "true"},
        decision_epoch=EPOCH,
        original=fake_original,
    )

    assert len(calls) == 2
    assert all(0.0 < value <= 300.0 for value in observed_budgets)
    assert observed_budgets[1] <= observed_budgets[0]
    assert result["provider_retry_passes"] == 2
    assert result["provider_retry_performed"] is True
    assert result["provider_retry_budget_extended"] is False
    assert result["provider_worker_limit_extended"] is False
    assert acquisition._fanout_budget_seconds is not canonical_budget


def test_successful_first_pass_is_not_repeated(monkeypatch) -> None:
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *args, **kwargs: 300.0)
    calls = []

    def fake_original(request_path, *, values, decision_epoch):
        del request_path, values, decision_epoch
        calls.append(1)
        return {"failed": 0, "provider_skipped_budget": 0, "completed": 13}

    result = resilient._run_resilient_fanout(
        "request.json",
        values={"RENDER": "true"},
        decision_epoch=EPOCH,
        original=fake_original,
    )

    assert calls == [1]
    assert result["provider_retry_passes"] == 1
    assert result["provider_retry_performed"] is False


def test_repeated_failures_never_exceed_bounded_pass_count(monkeypatch) -> None:
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *args, **kwargs: 300.0)
    calls = []

    def fake_original(request_path, *, values, decision_epoch):
        del request_path, values, decision_epoch
        calls.append(1)
        return {"failed": 1, "provider_skipped_budget": 0, "completed": 12}

    result = resilient._run_resilient_fanout(
        "request.json",
        values={"RENDER": "true"},
        decision_epoch=EPOCH,
        original=fake_original,
    )

    assert len(calls) == resilient._MAX_PROVIDER_PASSES
    assert result["provider_retry_passes"] == resilient._MAX_PROVIDER_PASSES
    assert result["provider_retry_budget_extended"] is False


def test_install_routes_future_sidecars_through_resilient_module(monkeypatch) -> None:
    monkeypatch.setattr(resilient._base, "_MODULE", "operations.original_prewarm")
    monkeypatch.delattr(resilient._base, resilient._INSTALLED_ATTR, raising=False)

    resilient.install()

    assert resilient._base._MODULE == resilient._MODULE
    assert getattr(resilient._base, resilient._INSTALLED_ATTR) is True
