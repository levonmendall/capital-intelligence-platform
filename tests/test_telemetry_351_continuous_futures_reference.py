from __future__ import annotations

from types import SimpleNamespace

from operations import cme_futures_reference_runtime
from operations import continuous_evidence_plane as plane
from operations import generalized_reference_readiness
from providers import cme_futures_reference_executable
from providers import massive_futures_reference_rate_resilient


def test_continuous_reference_preparer_uses_cme_primary_with_resilient_massive_fallback(
    monkeypatch,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/capital-intelligence-test",
        "CAPITAL_INTELLIGENCE_RELEASE": "telemetry-351-regression",
    }
    lineage_calls = 0
    prepared: dict[str, object] = {}

    class FakeMassiveFallback:
        pass

    class FakeCmePrimary:
        def __init__(self, *, fallback_provider, values):
            self.fallback_provider = fallback_provider
            self.values = values

    def install_lineage() -> None:
        nonlocal lineage_calls
        lineage_calls += 1

    def prepare_reference_readiness(received_values, **kwargs):
        prepared["values"] = received_values
        prepared.update(kwargs)
        return SimpleNamespace(manifest_id="reference:telemetry-351")

    monkeypatch.setattr(
        cme_futures_reference_runtime,
        "install_cme_futures_reference_lineage",
        install_lineage,
    )
    monkeypatch.setattr(
        cme_futures_reference_executable,
        "CmeExecutableFuturesReferenceProvider",
        FakeCmePrimary,
    )
    monkeypatch.setattr(
        massive_futures_reference_rate_resilient,
        "MassiveFuturesReferenceProvider",
        FakeMassiveFallback,
    )
    monkeypatch.setattr(
        generalized_reference_readiness,
        "prepare_reference_readiness",
        prepare_reference_readiness,
    )

    manifest = plane._default_reference_preparer(values)

    assert manifest.manifest_id == "reference:telemetry-351"
    assert lineage_calls == 1
    assert prepared["values"] is values
    provider = prepared["massive_futures_provider"]
    assert isinstance(provider, FakeCmePrimary)
    assert provider.values is values
    assert isinstance(provider.fallback_provider, FakeMassiveFallback)


def test_continuous_reference_preparer_does_not_use_legacy_massive_only_provider() -> None:
    source_names = plane._default_reference_preparer.__code__.co_names

    assert "massive_futures_reference_bounded" not in source_names
