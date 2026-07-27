from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from operations.provider_backfill import (
    ProviderBackfillError,
    ProviderBackfillPlan,
    ProviderBackfillRunner,
    ProviderBackfillState,
    ProviderBackfillTask,
    load_provider_backfill_plan,
)


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 5, tzinfo=timezone.utc)
AS_OF = datetime(2026, 7, 27, 23, 59, tzinfo=timezone.utc)


class FakeProvider:
    name = "FAKE"

    def __init__(self) -> None:
        self.queries: list[ProviderDatasetQuery] = []

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        self.queries.append(query)
        return ProviderDatasetSnapshot(
            query=query,
            provider=self.name,
            source_version="fake.v1",
            observed_at=query.end_at or query.as_of,
            available_at=query.as_of,
            retrieved_at=query.as_of,
            quality_state=DataQualityState.LIVE,
            availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            payload={
                "symbol": query.provider_symbol,
                "from": query.start_at.isoformat() if query.start_at else None,
                "to": query.end_at.isoformat() if query.end_at else None,
            },
        )


def task(*, required: bool = True) -> ProviderBackfillTask:
    return ProviderBackfillTask(
        identifier="prices",
        provider_factory="fake:build",
        dataset_type=ProviderDatasetType.MARKET_HISTORY,
        provider_symbols=("AAPL.US",),
        start_at=START,
        end_at=END,
        window_days=2,
        required=required,
    )


def test_provider_dataset_query_has_separate_end_and_knowledge_cutoff() -> None:
    query = ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.MARKET_HISTORY,
        provider_symbol="AAPL.US",
        start_at=START,
        end_at=END,
        as_of=AS_OF,
    )
    assert query.end_at == END
    with pytest.raises(ValueError, match="end_at cannot follow as_of"):
        ProviderDatasetQuery(
            dataset_type=ProviderDatasetType.MARKET_HISTORY,
            provider_symbol="AAPL.US",
            end_at=AS_OF,
            as_of=END,
        )


def test_backfill_windows_are_persisted_and_rerun_is_reused(tmp_path: Path) -> None:
    provider = FakeProvider()
    runner = ProviderBackfillRunner(provider_loader=lambda _: provider)
    plan = ProviderBackfillPlan(
        identifier="initial",
        as_of=AS_OF,
        tasks=(task(),),
    )
    first = runner.run(plan, output_directory=tmp_path, evaluated_at=AS_OF)
    assert first.state is ProviderBackfillState.COMPLETED
    assert len(first.artifacts) == 3
    assert all(not item.reused for item in first.artifacts)
    assert len(provider.queries) == 3
    assert provider.queries[0].end_at is not None
    assert (tmp_path / "backfill-report.json").exists()

    second = runner.run(plan, output_directory=tmp_path, evaluated_at=AS_OF)
    assert second.completed
    assert all(item.reused for item in second.artifacts)


def test_immutable_backfill_refuses_different_content(tmp_path: Path) -> None:
    provider = FakeProvider()
    runner = ProviderBackfillRunner(provider_loader=lambda _: provider)
    plan = ProviderBackfillPlan("initial", AS_OF, (task(),))
    assert runner.run(plan, output_directory=tmp_path, evaluated_at=AS_OF).completed
    artifact = next((tmp_path / "prices" / "AAPL.US").glob("*.json"))
    artifact.write_text('{"tampered":true}\n', encoding="utf-8")
    report = runner.run(plan, output_directory=tmp_path, evaluated_at=AS_OF)
    assert report.state is ProviderBackfillState.FAILED
    assert any("immutable backfill artifact differs" in item for item in report.failures)


def test_optional_failure_is_partial(tmp_path: Path) -> None:
    class Broken:
        name = "BROKEN"

        def fetch_dataset(self, query):
            raise RuntimeError("outage")

    report = ProviderBackfillRunner(provider_loader=lambda _: Broken()).run(
        ProviderBackfillPlan("optional", AS_OF, (task(required=False),)),
        output_directory=tmp_path,
        evaluated_at=AS_OF,
    )
    assert report.state is ProviderBackfillState.PARTIAL
    assert report.required_failures == ()


def test_plan_loader(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "provider-backfill-plan.v1",
                "identifier": "loaded",
                "as_of": AS_OF.isoformat(),
                "tasks": [
                    {
                        "identifier": "prices",
                        "provider_factory": "providers.eodhd:build_eodhd_provider",
                        "dataset_type": "market_history",
                        "provider_symbols": ["AAPL.US"],
                        "start_at": START.isoformat(),
                        "end_at": END.isoformat(),
                        "window_days": 30,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = load_provider_backfill_plan(path)
    assert plan.tasks[0].dataset_type is ProviderDatasetType.MARKET_HISTORY


def test_invalid_plan_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":"wrong","tasks":[]}', encoding="utf-8")
    with pytest.raises(ProviderBackfillError, match="unsupported"):
        load_provider_backfill_plan(path)
