"""Tests for asset-specific evidence and originating-fact lineage."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from application import (
    AssetSpecificEvidencePacket,
    MultiAssetEvidenceError,
    OriginatingFactObservation,
    SQLiteAssetSpecificEvidenceStore,
)
from cio import CandidateAssetClass

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CUTOFF = AS_OF + timedelta(minutes=5)


def _observations() -> tuple[OriginatingFactObservation, ...]:
    return (
        OriginatingFactObservation(
            observation_identifier="vendor-a:filing:1",
            originating_fact_identifier="origin:filing:1",
            source_family="primary-filing",
            source_identifier="issuer-filing:1",
            observed_at=AS_OF,
            available_at=AS_OF + timedelta(minutes=1),
        ),
        OriginatingFactObservation(
            observation_identifier="vendor-b:normalized:1",
            originating_fact_identifier="origin:filing:1",
            source_family="downstream-normalizer",
            source_identifier="vendor-b:feed",
            observed_at=AS_OF,
            available_at=AS_OF + timedelta(minutes=2),
        ),
        OriginatingFactObservation(
            observation_identifier="market:quote:1",
            originating_fact_identifier="origin:market:1",
            source_family="primary-market",
            source_identifier="venue:quote",
            observed_at=AS_OF,
            available_at=AS_OF,
        ),
    )


def _metrics(asset_class: CandidateAssetClass) -> tuple[tuple[str, float], ...]:
    common = (
        ("valuation_signal", 0.2),
        ("liquidity_score", 0.9),
        ("implementation_cost_return", 0.001),
    )
    if asset_class is CandidateAssetClass.CRYPTO:
        return common + (("supply_demand_signal", 0.3),)
    if asset_class is CandidateAssetClass.FX:
        return common + (("rate_differential", 0.015),)
    if asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
        return common + (
            ("fundamental_quality", 0.8),
            ("currency_exposure", 0.4),
        )
    raise AssertionError("unsupported asset class")


def _packet(asset_class: CandidateAssetClass) -> AssetSpecificEvidencePacket:
    return AssetSpecificEvidencePacket(
        identifier=f"asset-evidence:{asset_class.value}:candidate-1",
        screening_cycle_identifier="screening:multi-asset:1",
        candidate_identifier="candidate:1",
        instrument_identifier=f"instrument:{asset_class.value}:1",
        asset_class=asset_class,
        asset_class_approval_identifier=f"approval:{asset_class.value}:paper-v1",
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        fresh_until=CUTOFF + timedelta(hours=1),
        metrics=_metrics(asset_class),
        valuation_basis=("asset-specific valuation methodology",),
        return_drivers=("expected-return driver",),
        risks=("material risk",),
        invalidation_conditions=("valuation or liquidity condition changes",),
        observations=_observations(),
        provider_certification_identifiers=(
            f"provider-certification:{asset_class.value}:1",
        ),
        source_versions=(("asset-source", "v1"),),
        model_versions=(
            (f"{asset_class.value}_valuation", "v1"),
            (f"{asset_class.value}_expected_return", "v1"),
        ),
        limitations=("paper research only",),
    )


@pytest.mark.parametrize(
    "asset_class",
    (
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FX,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
    ),
)
def test_each_expanded_market_requires_a_complete_asset_packet(
    asset_class: CandidateAssetClass,
) -> None:
    packet = _packet(asset_class)

    assert packet.asset_class is asset_class
    assert packet.independent_origin_count == 2
    assert packet.originating_fact_identifiers == (
        "origin:filing:1",
        "origin:market:1",
    )
    assert len(packet.evidence_identifiers) == 3


def test_repeated_vendor_delivery_counts_as_one_originating_fact() -> None:
    packet = _packet(CandidateAssetClass.INTERNATIONAL_EQUITY)

    assert len(packet.observations) == 3
    assert packet.independent_origin_count == 2
    assert packet.observations[0].originating_fact_identifier == (
        packet.observations[1].originating_fact_identifier
    )


def test_missing_asset_specific_metric_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing required metrics"):
        AssetSpecificEvidencePacket(
            identifier="asset-evidence:fx:incomplete",
            screening_cycle_identifier="screening:1",
            candidate_identifier="candidate:1",
            instrument_identifier="instrument:fx:1",
            asset_class=CandidateAssetClass.FX,
            asset_class_approval_identifier="approval:fx:1",
            as_of=AS_OF,
            knowledge_cutoff=CUTOFF,
            fresh_until=CUTOFF + timedelta(hours=1),
            metrics=(("valuation_signal", 0.1),),
            valuation_basis=("basis",),
            return_drivers=("driver",),
            risks=("risk",),
            invalidation_conditions=("condition",),
            observations=_observations(),
            provider_certification_identifiers=("cert:1",),
            source_versions=(("source", "v1"),),
            model_versions=(("model", "v1"),),
            limitations=("paper",),
        )


def test_future_known_or_stale_asset_evidence_is_rejected() -> None:
    future = OriginatingFactObservation(
        observation_identifier="future:1",
        originating_fact_identifier="origin:future:1",
        source_family="future",
        source_identifier="source:future",
        observed_at=AS_OF,
        available_at=CUTOFF + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="unavailable at the knowledge cutoff"):
        AssetSpecificEvidencePacket(
            identifier="asset-evidence:crypto:future",
            screening_cycle_identifier="screening:1",
            candidate_identifier="candidate:1",
            instrument_identifier="instrument:crypto:1",
            asset_class=CandidateAssetClass.CRYPTO,
            asset_class_approval_identifier="approval:crypto:1",
            as_of=AS_OF,
            knowledge_cutoff=CUTOFF,
            fresh_until=CUTOFF + timedelta(hours=1),
            metrics=_metrics(CandidateAssetClass.CRYPTO),
            valuation_basis=("basis",),
            return_drivers=("driver",),
            risks=("risk",),
            invalidation_conditions=("condition",),
            observations=(future,),
            provider_certification_identifiers=("cert:1",),
            source_versions=(("source", "v1"),),
            model_versions=(("model", "v1"),),
            limitations=("paper",),
        )

    with pytest.raises(ValueError, match="stale"):
        AssetSpecificEvidencePacket(
            identifier="asset-evidence:crypto:stale",
            screening_cycle_identifier="screening:1",
            candidate_identifier="candidate:1",
            instrument_identifier="instrument:crypto:1",
            asset_class=CandidateAssetClass.CRYPTO,
            asset_class_approval_identifier="approval:crypto:1",
            as_of=AS_OF,
            knowledge_cutoff=CUTOFF,
            fresh_until=CUTOFF - timedelta(seconds=1),
            metrics=_metrics(CandidateAssetClass.CRYPTO),
            valuation_basis=("basis",),
            return_drivers=("driver",),
            risks=("risk",),
            invalidation_conditions=("condition",),
            observations=_observations(),
            provider_certification_identifiers=("cert:1",),
            source_versions=(("source", "v1"),),
            model_versions=(("model", "v1"),),
            limitations=("paper",),
        )


def test_packet_must_match_the_screened_candidate_and_cutoff() -> None:
    packet = _packet(CandidateAssetClass.FX)
    packet.require_match(
        screening_cycle_identifier="screening:multi-asset:1",
        candidate_identifier="candidate:1",
        instrument_identifier="instrument:fx:1",
        asset_class=CandidateAssetClass.FX,
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
    )

    with pytest.raises(MultiAssetEvidenceError, match="instrument_identifier"):
        packet.require_match(
            screening_cycle_identifier="screening:multi-asset:1",
            candidate_identifier="candidate:1",
            instrument_identifier="instrument:fx:other",
            asset_class=CandidateAssetClass.FX,
            as_of=AS_OF,
            knowledge_cutoff=CUTOFF,
        )


def test_asset_evidence_store_is_exact_idempotent_and_append_only(
    tmp_path: Path,
) -> None:
    store = SQLiteAssetSpecificEvidenceStore(tmp_path / "asset-evidence.db")
    crypto = _packet(CandidateAssetClass.CRYPTO)
    fx = AssetSpecificEvidencePacket.from_dict(
        {
            **_packet(CandidateAssetClass.FX).to_dict(),
            "candidate_identifier": "candidate:2",
            "identifier": "asset-evidence:fx:candidate-2",
            "instrument_identifier": "instrument:fx:2",
        }
    )

    assert store.append(crypto) == 1
    assert store.append(crypto) == 1
    assert store.append(fx) == 2
    assert store.packets_for_cycle(
        "screening:multi-asset:1",
        as_of=AS_OF,
    ) == (crypto, fx)
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE asset_specific_evidence_packets SET payload_json = '{}' WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM asset_specific_evidence_packets")
