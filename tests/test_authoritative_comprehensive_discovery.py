from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import all_market_lane_certification as lane
from operations import authoritative_comprehensive_discovery as authoritative
from operations import persistent_certification_scheduler as scheduler
from operations.comprehensive_market_discovery_legacy import (
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
)


def _record() -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol="BTCUSD",
        provider_symbol="BTC/USD",
        name="Bitcoin",
        asset_class=CandidateAssetClass.CRYPTO,
        economic_exposure="crypto",
        venue="MULTI",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="crypto",
        provider_kind="provider-neutral",
        source_identifier="test-catalog",
    )


def _features(as_of: datetime) -> DiscoveryMarketFeatures:
    return DiscoveryMarketFeatures(
        price=60_000.0,
        observed_at=as_of,
        one_month_return=0.02,
        three_month_return=0.04,
        six_month_return=0.08,
        twelve_month_return=0.16,
        annualized_volatility=0.45,
        maximum_drawdown=-0.20,
        average_daily_dollar_volume=2_000_000_000.0,
        history_bars=760,
        evidence_identifiers=("provider:test",),
    )


def _values(tmp_path, release: str) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
    }


def _node(as_of: datetime) -> scheduler.CertificationNode:
    return scheduler.CertificationNode(
        node_id="deep-market-evidence:crypto",
        asset_class="crypto",
        provider_groups=("alpaca", "coinbase", "kraken"),
        input_fingerprint="same-governed-input",
        deadline=as_of + timedelta(minutes=15),
        decision_eligible_count=1,
    )


def _raise_synthetic_provider_timeout(_node: scheduler.CertificationNode) -> int:
    """Top-level so the production spawn contract can preserve child failure type."""

    raise TimeoutError("synthetic provider timeout")


def test_compatible_lane_checkpoint_rebinds_without_provider_call(tmp_path) -> None:
    as_of = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)
    policy = SimpleNamespace(version="policy-v1")
    records = (_record(),)
    node = _node(as_of)
    first_release = "a" * 40
    second_release = "b" * 40
    first_values = _values(tmp_path, first_release)

    calls = {"provider": 0}

    def provider_probe(records, epoch, policy):
        del records, policy
        calls["provider"] += 1
        return {"BTCUSD": _features(epoch)}

    observed = lane.checkpointed_market_probe(
        provider_probe,
        DiscoveryMarketFeatures,
        records,
        as_of,
        policy,
        values=first_values,
    )
    assert observed["BTCUSD"].price == 60_000.0
    assert calls == {"provider": 1}

    authoritative._publish_compatible_checkpoint(
        first_values,
        release_sha=first_release,
        node=node,
        records=records,
        epoch=as_of,
        policy_version=policy.version,
    )

    second_values = _values(tmp_path, second_release)
    assert authoritative._rebind_compatible_checkpoint(
        second_values,
        release_sha=second_release,
        node=node,
        records=records,
        epoch=as_of,
        policy_version=policy.version,
    )

    def forbidden_provider_probe(records, epoch, policy):
        del records, epoch, policy
        raise AssertionError("provider acquisition must not run after compatibility rebind")

    rebound = lane.checkpointed_market_probe(
        forbidden_provider_probe,
        DiscoveryMarketFeatures,
        records,
        as_of,
        policy,
        values=second_values,
    )
    assert rebound["BTCUSD"].evidence_identifiers == ("provider:test",)


def test_compatible_lane_checkpoint_does_not_cross_epoch(tmp_path) -> None:
    first_epoch = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)
    second_epoch = first_epoch + timedelta(minutes=1)
    policy = SimpleNamespace(version="policy-v1")
    records = (_record(),)
    node = _node(first_epoch)
    first_release = "a" * 40
    first_values = _values(tmp_path, first_release)

    lane.checkpointed_market_probe(
        lambda records, epoch, policy: {"BTCUSD": _features(epoch)},
        DiscoveryMarketFeatures,
        records,
        first_epoch,
        policy,
        values=first_values,
    )
    authoritative._publish_compatible_checkpoint(
        first_values,
        release_sha=first_release,
        node=node,
        records=records,
        epoch=first_epoch,
        policy_version=policy.version,
    )

    assert not authoritative._rebind_compatible_checkpoint(
        _values(tmp_path, "b" * 40),
        release_sha="b" * 40,
        node=node,
        records=records,
        epoch=second_epoch,
        policy_version=policy.version,
    )


def test_scheduler_failure_detail_promotes_exact_lane(tmp_path) -> None:
    as_of = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)
    release = "c" * 40
    values = _values(tmp_path, release)
    node = _node(as_of)
    runner = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha=release,
        epoch=as_of,
        policy_version="policy-v1",
    )

    with pytest.raises(scheduler.CertificationSchedulerError) as captured:
        runner.run((node,), _raise_synthetic_provider_timeout)

    detail = authoritative._failure_detail(
        values,
        release_sha=release,
        epoch=as_of,
        nodes=(node,),
        error=captured.value,
    )
    assert "node=deep-market-evidence:crypto" in detail
    assert "asset_class=crypto" in detail
    assert "failure_type=TimeoutError" in detail
    assert "required_nodes=1" in detail
