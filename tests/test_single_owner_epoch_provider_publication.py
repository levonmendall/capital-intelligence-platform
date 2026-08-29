from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations import cached_transactional_comprehensive_discovery_lane as cached_lane
from operations import comprehensive_discovery_structural_prewarm as overlap


def _as_of() -> datetime:
    return datetime(2026, 8, 28, 15, 27, tzinfo=timezone.utc)


def test_us_equity_overlap_uses_exact_comprehensive_request_identity(monkeypatch, tmp_path) -> None:
    from operations import comprehensive_discovery_input_spool as spool
    from operations import comprehensive_market_discovery as facade
    from operations import evidence_state_scope as state_scope
    from operations import epoch_scoped_provider_acquisition as acquisition

    policy = SimpleNamespace(version="policy-v1")
    request_path = tmp_path / "request.json"
    observed: dict[str, object] = {}

    monkeypatch.setattr(overlap, "_eligible", lambda values: True)
    monkeypatch.setattr(
        facade,
        "_core",
        SimpleNamespace(ComprehensiveMarketDiscoveryPolicy=lambda: policy),
    )
    monkeypatch.setattr(
        state_scope,
        "load_evidence_state_scope",
        lambda *, as_of, values: SimpleNamespace(
            held_symbols=("HELD",),
            tracked_symbols=("TRACKED",),
        ),
    )

    def fake_prepare_request(**kwargs):
        observed["request"] = kwargs
        return SimpleNamespace(path=request_path)

    def fake_fanout(path, *, values, decision_epoch):
        observed["fanout_path"] = Path(path)
        observed["fanout_values"] = dict(values)
        observed["fanout_epoch"] = decision_epoch
        return {"attempted": True, "completed": 5, "failed": 0}

    monkeypatch.setattr(spool, "prepare_request", fake_prepare_request)
    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }
    result = overlap.prewarm_epoch_provider_inputs(
        evidence_as_of=_as_of(),
        values=values,
    )

    request = observed["request"]
    assert request["values"] == values
    assert request["decision_epoch"] == _as_of()
    assert request["held_symbols"] == ("HELD",)
    assert request["tracked_symbols"] == ("TRACKED",)
    # The stage-owned comprehensive call uses its default empty exclusion set and policy.
    assert request["excluded_symbols"] == ()
    assert request["policy"] is policy
    assert observed["fanout_path"] == request_path
    assert observed["fanout_epoch"] == _as_of()
    assert result == {"attempted": True, "completed": 5, "failed": 0}


def test_transactional_publication_reuses_valid_epoch_artifact_without_network(monkeypatch, tmp_path) -> None:
    publication = cached_lane._canonical._publication
    expected = SimpleNamespace(
        path=tmp_path / "provider.json",
        catalog_count=1,
        limitations=(),
        reused=True,
    )

    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication._core, "_publication_path", lambda policy: expected.path)
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: expected)

    result = cached_lane._reuse_only_provider_preselection_publication(
        {"lane": (object(),)},
        as_of=_as_of(),
        policy=SimpleNamespace(preselection_freshness_days=3),
        market_probe=lambda *args: (_ for _ in ()).throw(
            AssertionError("reuse-only publication must never call a provider")
        ),
    )

    assert result is expected


def test_transactional_publication_missing_artifact_fails_without_network(monkeypatch, tmp_path) -> None:
    publication = cached_lane._canonical._publication

    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication._core, "_publication_path", lambda policy: tmp_path / "missing.json")
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: None)

    with pytest.raises(
        publication.ProviderPreselectionPublicationError,
        match="refuses late provider reacquisition",
    ):
        cached_lane._reuse_only_provider_preselection_publication(
            {"lane": (object(),)},
            as_of=_as_of(),
            policy=SimpleNamespace(preselection_freshness_days=3),
            market_probe=lambda *args: (_ for _ in ()).throw(
                AssertionError("missing early publication must fail, not reacquire")
            ),
        )


def test_transactional_publication_rejects_limited_epoch_artifact(monkeypatch, tmp_path) -> None:
    publication = cached_lane._canonical._publication
    limited = SimpleNamespace(
        path=tmp_path / "provider.json",
        catalog_count=1,
        limitations=("provider degraded",),
        reused=True,
    )

    monkeypatch.setattr(publication._core, "_aware", lambda value, *, field_name: value)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication._core, "_publication_path", lambda policy: limited.path)
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: limited)

    with pytest.raises(
        publication.ProviderPreselectionPublicationError,
        match="refuses degraded provider evidence",
    ):
        cached_lane._reuse_only_provider_preselection_publication(
            {"lane": (object(),)},
            as_of=_as_of(),
            policy=SimpleNamespace(preselection_freshness_days=3),
        )


def test_existing_epoch_budget_and_authority_bounds_are_unchanged() -> None:
    from operations import epoch_scoped_provider_acquisition as acquisition

    assert acquisition._MAX_FANOUT_SECONDS == 300.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0
    assert acquisition._DEFAULT_WORKERS == 6
    assert acquisition._MAX_WORKERS == 6
