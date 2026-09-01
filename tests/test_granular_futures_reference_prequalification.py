from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from operations import cme_futures_reference_runtime as runtime
from operations import supervised_reference_prequalification as reference
from operations.granular_futures_reference_prequalification import (
    GranularFuturesReferenceProvider,
    load_futures_reference_progress,
)
from operations.supervised_component_execution import (
    SupervisedComponentExecutionError,
    SupervisedComponentTimeout,
)
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


AS_OF = datetime(2026, 8, 18, 1, 30, tzinfo=timezone.utc)


def _contract(root: str, ticker: str, *, source: str) -> MassiveFuturesContract:
    return MassiveFuturesContract(
        ticker=ticker,
        product_code=root,
        trading_venue="CME",
        first_trade_date="2026-01-01",
        last_trade_date="2026-12-18",
        settlement_date="2026-12-18",
        active=True,
        source_identifier=source,
    )


class _FakeCme:
    file_urls = (("CME", "cme://fprf"), ("NYMEX", "nymex://fprf"))

    def __init__(self) -> None:
        self.cache: dict[
            tuple[str, tuple[str, ...]],
            tuple[tuple[MassiveFuturesContract, ...], tuple[date, ...]],
        ] = {}
        self.complete_cache = None
        self.complete_cache_writes = 0
        self.nymex_ready = False

    @staticmethod
    def _complete(rows, roots) -> bool:
        covered = {
            row.product_code.strip().upper()
            for row in rows
            if row.active
        }
        return set(roots).issubset(covered)

    @staticmethod
    def _source_dates_current(_dates, _reference_date) -> bool:
        return True

    def _records_from_cache(self, *, roots, as_of):
        del roots, as_of
        return self.complete_cache

    def _write_cache(self, *, roots, captured_at, business_dates, contracts):
        del roots, captured_at, business_dates
        self.complete_cache = tuple(contracts)
        self.complete_cache_writes += 1

    def _records_from_venue_cache(self, *, venue, roots, as_of):
        del as_of
        return self.cache.get((venue, tuple(roots)))

    def _write_venue_cache(
        self,
        *,
        venue,
        roots,
        captured_at,
        business_dates,
        contracts,
    ):
        del captured_at
        self.cache[(venue, tuple(roots))] = (
            tuple(contracts),
            tuple(business_dates),
        )

    def _collect_file(self, *, exchange_name, url, roots, reference_date):
        del url
        if exchange_name == "CME":
            rows = (
                _contract(
                    "ES",
                    "ESZ6",
                    source=f"cme-fprf:cme:ES:202612:{reference_date.isoformat()}",
                ),
            )
        elif exchange_name == "NYMEX" and self.nymex_ready:
            rows = (
                _contract(
                    "CL",
                    "CLZ6",
                    source=f"cme-fprf:nymex:CL:202612:{reference_date.isoformat()}",
                ),
            )
        else:
            rows = ()
        return (
            list(row for row in rows if row.product_code in roots),
            {reference_date},
            {"exchange": exchange_name},
        )


class _FakeMassive:
    def _load_root_cache(self, *, root, as_of):
        del root, as_of
        return None

    def futures_contracts(self, **_kwargs):
        raise AssertionError("Massive network operation should be controlled by the runner")


def test_root_checkpoint_survives_later_venue_and_fallback_timeout(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-granular",
        "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS": "5",
    }
    cme = _FakeCme()
    first_calls: list[str] = []

    def first_runner(*, component, operation, timeout_seconds, return_value):
        del timeout_seconds, return_value
        first_calls.append(component)
        if component in {"cme-venue-nymex", "massive-root-CL"}:
            raise SupervisedComponentTimeout(f"{component} exceeded budget")
        return operation()

    provider = GranularFuturesReferenceProvider(
        values=values,
        cme_provider=cme,
        massive_provider_factory=_FakeMassive,
        component_runner=first_runner,
        clock=lambda: AS_OF,
    )

    with pytest.raises(
        MassiveMultiAssetError,
        match=r"failure_type=timeout.*unresolved_roots=CL",
    ):
        provider.futures_contracts(
            as_of=AS_OF,
            product_codes=("ES", "CL"),
        )

    assert first_calls == [
        "cme-venue-cme",
        "cme-venue-nymex",
        "massive-root-CL",
    ]
    assert ("CME", ("ES",)) in cme.cache

    progress = load_futures_reference_progress(values)
    assert progress is not None
    assert progress["state"] == "incomplete"
    assert progress["qualified_roots"] == ["ES"]
    assert progress["unresolved_roots"] == ["CL"]
    assert any(
        row["unit"] == "massive-root-CL"
        and row["state"] == "timed-out"
        and row["root"] == "CL"
        for row in progress["units"]
    )

    cme.nymex_ready = True
    second_calls: list[str] = []

    def second_runner(*, component, operation, timeout_seconds, return_value):
        del timeout_seconds, return_value
        second_calls.append(component)
        if component == "cme-venue-cme":
            pytest.fail("qualified CME root must be reused instead of recollected")
        return operation()

    retry = GranularFuturesReferenceProvider(
        values=values,
        cme_provider=cme,
        massive_provider_factory=_FakeMassive,
        component_runner=second_runner,
        clock=lambda: AS_OF,
    )
    rows = retry.futures_contracts(
        as_of=AS_OF,
        product_codes=("ES", "CL"),
    )

    assert {row.product_code for row in rows} == {"ES", "CL"}
    assert second_calls == ["cme-venue-nymex"]
    assert cme.complete_cache_writes == 1

    qualified = load_futures_reference_progress(values)
    assert qualified is not None
    assert qualified["state"] == "qualified"
    assert qualified["qualified_roots"] == ["CL", "ES"]
    assert qualified["unresolved_roots"] == []


def test_futures_runtime_bypasses_only_obsolete_aggregate_supervisor(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def original(*, values, component, provider, operation, return_value):
        del values, provider, return_value
        calls.append(component)
        return operation()

    monkeypatch.setattr(reference, "_run_component", original)
    runtime._install_reference_supervisor_adapter()

    futures_result = reference._run_component(
        values={},
        component=reference._FUTURES,
        provider="cme-massive",
        operation=lambda: "futures-direct",
        return_value=False,
    )
    assert futures_result == "futures-direct"
    assert calls == []

    directory_result = reference._run_component(
        values={},
        component=reference._DIRECTORY,
        provider="eodhd",
        operation=lambda: "directory-supervised",
        return_value=False,
    )
    assert directory_result == "directory-supervised"
    assert calls == [reference._DIRECTORY]


def test_unit_timeout_configuration_is_fail_closed(tmp_path) -> None:
    cme = _FakeCme()
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-invalid-timeout",
        "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS": "0",
    }
    provider = GranularFuturesReferenceProvider(
        values=values,
        cme_provider=cme,
        massive_provider_factory=_FakeMassive,
        component_runner=lambda **_kwargs: (),
        clock=lambda: AS_OF,
    )

    with pytest.raises(ValueError, match="must be positive"):
        provider.futures_contracts(
            as_of=AS_OF,
            product_codes=("ES",),
        )


def test_failed_cme_venues_defer_all_roots_to_one_bounded_fallback_batch(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-batched-fallback",
        "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS": "45",
        "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_FALLBACK_MAX_WORKERS": "3",
    }
    cme = _FakeCme()
    primary_calls: list[str] = []
    batches: list[tuple[tuple[str, ...], float, int]] = []

    def failed_primary(*, component, operation, timeout_seconds, return_value):
        del operation, timeout_seconds, return_value
        primary_calls.append(component)
        raise SupervisedComponentExecutionError(
            f"{component} failed: MassiveMultiAssetError: CME returned HTTP 400",
            remote_error_type="MassiveMultiAssetError",
            status_code=400,
            retryable=False,
        )

    def fallback_batch(*, components, timeout_seconds, maximum_parallel):
        batches.append((tuple(components), timeout_seconds, maximum_parallel))
        return {
            "massive-root-CL": (_contract("CL", "CLZ6", source="massive:CL"),),
            "massive-root-ES": (_contract("ES", "ESZ6", source="massive:ES"),),
        }

    provider = GranularFuturesReferenceProvider(
        values=values,
        cme_provider=cme,
        massive_provider_factory=_FakeMassive,
        component_runner=failed_primary,
        batch_component_runner=fallback_batch,
        clock=lambda: AS_OF,
    )

    rows = provider.futures_contracts(as_of=AS_OF, product_codes=("ES", "CL"))

    assert {row.product_code for row in rows} == {"CL", "ES"}
    assert primary_calls == ["cme-venue-cme", "cme-venue-nymex"]
    assert batches == [(("massive-root-ES", "massive-root-CL"), 45.0, 3)]
    progress = load_futures_reference_progress(values)
    assert progress is not None and progress["state"] == "qualified"
    cme_failures = [
        unit for unit in progress["units"] if unit["provider"] == "cme_fprf"
    ]
    assert {unit["http_status"] for unit in cme_failures} == {400}
    assert {unit["provider_error_type"] for unit in cme_failures} == {
        "MassiveMultiAssetError"
    }


def test_fallback_worker_configuration_is_fail_closed(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-invalid-workers",
        "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_FALLBACK_MAX_WORKERS": "5",
    }
    cme = _FakeCme()

    def failed_primary(**_kwargs):
        raise SupervisedComponentTimeout("primary timed out")

    provider = GranularFuturesReferenceProvider(
        values=values,
        cme_provider=cme,
        massive_provider_factory=_FakeMassive,
        component_runner=failed_primary,
        batch_component_runner=lambda **_kwargs: {},
        clock=lambda: AS_OF,
    )

    with pytest.raises(ValueError, match="must be between 1 and 4"):
        provider.futures_contracts(as_of=AS_OF, product_codes=("ES", "CL"))
