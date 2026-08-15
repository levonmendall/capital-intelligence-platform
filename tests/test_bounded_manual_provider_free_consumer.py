from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_entrypoint():
    path = Path(__file__).resolve().parents[1] / "run_bounded_manual_cio_diagnostic.py"
    spec = importlib.util.spec_from_file_location(
        "bounded_manual_cio_provider_free_test_entrypoint",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_cio_child_disables_public_provider_collection(monkeypatch) -> None:
    runtime = _load_entrypoint()
    monkeypatch.setattr(runtime, "evidence_plane_enabled", lambda _values: True)
    values = {
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED": "true",
    }

    configured = runtime._configure_provider_free_consumer(values)

    assert configured is True
    assert values["CAPITAL_INTELLIGENCE_CIO_PROVIDER_FREE_CONSUMER"] == "true"
    assert values["CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED"] == "false"


def test_nonproduction_caller_preserves_public_collection_setting(monkeypatch) -> None:
    runtime = _load_entrypoint()
    monkeypatch.setattr(runtime, "evidence_plane_enabled", lambda _values: False)
    values = {
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED": "true",
    }

    configured = runtime._configure_provider_free_consumer(values)

    assert configured is False
    assert values["CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED"] == "true"
    assert "CAPITAL_INTELLIGENCE_CIO_PROVIDER_FREE_CONSUMER" not in values
