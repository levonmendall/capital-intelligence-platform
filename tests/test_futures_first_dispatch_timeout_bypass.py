from __future__ import annotations

import inspect

from operations import cme_futures_reference_runtime as runtime
from operations import granular_futures_reference_prequalification as granular
from operations import supervised_reference_prequalification as reference


def test_prepare_installs_granular_runtime_before_any_component_dispatch() -> None:
    source = inspect.getsource(reference.prepare_supervised_reference_prequalification)

    assert source.index("_install_futures_runtime()") < source.index("_run_component(")


def test_first_futures_dispatch_bypasses_only_obsolete_aggregate_supervisor(monkeypatch) -> None:
    aggregate_calls: list[str] = []

    def aggregate_runner(*, values, component, provider, operation, return_value):
        aggregate_calls.append(component)
        return operation()

    monkeypatch.setattr(reference, "_run_component", aggregate_runner)
    monkeypatch.setattr(runtime, "_install_lineage_adapter", lambda: None)
    monkeypatch.setattr(runtime, "_install_granular_provider_adapter", lambda: None)

    reference._install_futures_runtime()

    assert reference._run_component(
        values={},
        component=reference._FUTURES,
        provider="cme-massive",
        operation=lambda: "futures-ok",
        return_value=False,
    ) == "futures-ok"
    assert aggregate_calls == []

    assert reference._run_component(
        values={},
        component=reference._DIRECTORY,
        provider="eodhd",
        operation=lambda: "directory-ok",
        return_value=False,
    ) == "directory-ok"
    assert aggregate_calls == [reference._DIRECTORY]


def test_repair_does_not_extend_existing_timeout_contracts() -> None:
    assert reference._DEFAULT_TIMEOUT_SECONDS == 120.0
    assert granular._DEFAULT_UNIT_TIMEOUT_SECONDS == 45.0
