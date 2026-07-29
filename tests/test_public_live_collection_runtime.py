from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from public_live_collection_runtime import collect_public_live_information_if_due


class _Record:
    def to_dict(self):
        return {"identifier": "record-1", "real_money_authorized": False}


class _Source:
    def __init__(self, *, succeeded: bool):
        self.succeeded = succeeded


class _Report:
    def __init__(
        self,
        *,
        evaluated_at: datetime,
        required_sources_ready: bool = True,
        source_states: tuple[bool, ...] = (True, True),
    ) -> None:
        self.catalog_identifier = "public-catalog:test"
        self.evaluated_at = evaluated_at
        self.required_sources_ready = required_sources_ready
        self.sources = tuple(_Source(succeeded=value) for value in source_states)
        self.records = (_Record(),)

    def to_dict(self, *, include_records: bool):
        assert include_records is False
        return {
            "schema_version": "public-live-information-report.v1",
            "catalog_identifier": self.catalog_identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "required_sources_ready": self.required_sources_ready,
            "source_count": len(self.sources),
            "record_count": len(self.records),
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        }


class _Provider:
    def __init__(self, report: _Report, calls: list[bool]) -> None:
        self._report = report
        self._calls = calls

    def collect(self, *, include_optional: bool):
        self._calls.append(include_optional)
        return self._report


def _configure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS",
        "3600",
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED",
        "true",
    )


def test_runtime_collector_runs_immediately_then_observes_hourly_window(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    now = datetime(2026, 7, 29, 13, 20, tzinfo=timezone.utc)
    calls: list[bool] = []
    report = _Report(evaluated_at=now)

    def factory(_catalog):
        return _Provider(report, calls)

    first = collect_public_live_information_if_due(
        now=now,
        provider_factory=factory,
    )
    second = collect_public_live_information_if_due(
        now=now + timedelta(minutes=30),
        provider_factory=factory,
    )
    third = collect_public_live_information_if_due(
        now=now + timedelta(hours=1, seconds=1),
        provider_factory=lambda _catalog: _Provider(
            _Report(evaluated_at=now + timedelta(hours=1, seconds=1)),
            calls,
        ),
    )

    assert first.state == "available"
    assert second.state == "not_due"
    assert third.state == "available"
    assert calls == [True, True]
    assert (tmp_path / "public-live-information-report.json").exists()
    assert (tmp_path / "public-live-information-records.json").exists()
    state = json.loads(
        (tmp_path / "public-live-information-runtime-state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["interval_seconds"] == 3600
    assert state["real_money_authorized"] is False


def test_required_source_outage_is_persisted_as_degraded_not_available(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    now = datetime(2026, 7, 29, 13, 20, tzinfo=timezone.utc)
    report = _Report(
        evaluated_at=now,
        required_sources_ready=False,
        source_states=(True, False),
    )

    result = collect_public_live_information_if_due(
        now=now,
        provider_factory=lambda _catalog: _Provider(report, []),
    )

    assert result.state == "degraded"
    assert result.exit_code == 3
    assert result.required_sources_ready is False
    assert result.failed_source_count == 1


def test_collector_implementation_failure_is_recorded_without_raising(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    now = datetime(2026, 7, 29, 13, 20, tzinfo=timezone.utc)

    class BrokenProvider:
        def collect(self, *, include_optional: bool):
            raise RuntimeError("collector unavailable")

    result = collect_public_live_information_if_due(
        now=now,
        provider_factory=lambda _catalog: BrokenProvider(),
    )

    assert result.state == "failed"
    assert result.exit_code == 4
    state = json.loads(
        (tmp_path / "public-live-information-runtime-state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["state"] == "failed"
    assert state["real_money_authorized"] is False


def test_force_collection_bypasses_hourly_window(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    now = datetime(2026, 7, 29, 13, 20, tzinfo=timezone.utc)
    calls: list[bool] = []

    def factory(evaluated_at):
        return lambda _catalog: _Provider(_Report(evaluated_at=evaluated_at), calls)

    collect_public_live_information_if_due(
        now=now,
        provider_factory=factory(now),
    )
    forced = collect_public_live_information_if_due(
        now=now + timedelta(minutes=5),
        force=True,
        provider_factory=factory(now + timedelta(minutes=5)),
    )

    assert forced.state == "available"
    assert calls == [True, True]
