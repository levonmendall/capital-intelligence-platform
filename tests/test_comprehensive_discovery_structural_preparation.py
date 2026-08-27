from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import comprehensive_discovery_input_spool as spool
from operations import comprehensive_discovery_structural_preparation as structural
from operations import transactional_comprehensive_discovery_lane as transaction


_NOW = datetime(2026, 8, 27, 5, 30, tzinfo=timezone.utc)


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-structural-test",
        structural._REFERENCE_MANIFEST_ID_ENV: "reference-manifest-1",
    }


def test_structural_preparation_contains_reference_catalogs_only(tmp_path, monkeypatch) -> None:
    values = _values(tmp_path)
    active = (
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.OPTION,
    )
    reference = frozenset(
        {CandidateAssetClass.INTERNATIONAL_EQUITY, CandidateAssetClass.FUTURE}
    )
    monkeypatch.setattr(structural, "_active_lanes", lambda _timestamp: active)
    monkeypatch.setattr(structural, "_reference_lane_set", lambda: reference)
    calls: list[CandidateAssetClass] = []

    def load_records(*, values, timestamp, asset_class):
        del values, timestamp
        calls.append(asset_class)
        return (SimpleNamespace(asset_class=asset_class, symbol=asset_class.value),)

    monkeypatch.setattr(structural, "_load_reference_lane_records", load_records)

    manifest = structural.prepare_structural_reference_catalogs(
        values,
        reference_manifest_id="reference-manifest-1",
        preparation_as_of=_NOW,
    )

    assert calls == [CandidateAssetClass.FUTURE, CandidateAssetClass.INTERNATIONAL_EQUITY]
    assert manifest.reference_lanes == ("future", "international_equity")
    assert "option" not in manifest.reference_lanes
    body = spool._load_json(manifest.path, schema=structural._SCHEMA_VERSION)
    assert body["structural_only"] is True
    assert body["market_evidence_included"] is False
    assert body["option_evidence_included"] is False
    assert body["provider_preselection_included"] is False
    assert body["terminal_screening_included"] is False
    assert body["evidence_certified"] is False
    assert body["freshness_epoch_authority"] is False
    assert body["decision_authority"] is False
    assert body["execution_authority"] is False
    assert body["paper_only"] is True
    assert body["real_money_authorized"] is False


def test_fresh_epoch_binds_only_matching_reference_and_schedule(tmp_path, monkeypatch) -> None:
    values = _values(tmp_path)
    active = (CandidateAssetClass.INTERNATIONAL_EQUITY, CandidateAssetClass.OPTION)
    monkeypatch.setattr(structural, "_active_lanes", lambda _timestamp: active)
    monkeypatch.setattr(
        structural,
        "_reference_lane_set",
        lambda: frozenset({CandidateAssetClass.INTERNATIONAL_EQUITY}),
    )
    monkeypatch.setattr(
        structural,
        "_load_reference_lane_records",
        lambda **_kwargs: (
            SimpleNamespace(
                asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
                symbol="INTL",
            ),
        ),
    )
    manifest = structural.prepare_structural_reference_catalogs(
        values,
        reference_manifest_id="reference-manifest-1",
        preparation_as_of=_NOW,
    )

    bound = structural.bind_structural_manifest_for_fresh_epoch(
        values,
        reference_manifest_id="reference-manifest-1",
        exact_as_of=_NOW,
    )
    assert bound.manifest_id == manifest.manifest_id
    records = structural.load_bound_reference_lane_records(
        values,
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        exact_as_of=_NOW,
    )
    assert tuple(item.symbol for item in records) == ("INTL",)

    with pytest.raises(spool.ComprehensiveDiscoverySpoolError, match="reference binding"):
        structural.load_structural_manifest(
            manifest.path,
            values=values,
            reference_manifest_id="different-reference",
            exact_as_of=_NOW,
        )

    monkeypatch.setattr(
        structural,
        "_active_lanes",
        lambda _timestamp: (CandidateAssetClass.INTERNATIONAL_EQUITY,),
    )
    with pytest.raises(spool.ComprehensiveDiscoverySpoolError, match="scheduled-lane scope"):
        structural.load_structural_manifest(
            manifest.path,
            values=values,
            reference_manifest_id="reference-manifest-1",
            exact_as_of=_NOW,
        )


def test_transaction_uses_bound_structure_for_reference_but_not_options(monkeypatch) -> None:
    exact = _NOW
    structural_calls: list[tuple[CandidateAssetClass, datetime]] = []
    option_calls: list[datetime] = []

    class Legacy:
        @staticmethod
        def _option_catalog(*, as_of, config, policy):
            del config, policy
            option_calls.append(as_of)
            return (SimpleNamespace(asset_class=CandidateAssetClass.OPTION),)

    class Base:
        _legacy = Legacy()

        @staticmethod
        def load_comprehensive_market_discovery_config():
            return object()

        @staticmethod
        def scheduled_discovery_lanes(_timestamp):
            return {CandidateAssetClass.INTERNATIONAL_EQUITY, CandidateAssetClass.OPTION}

    core = SimpleNamespace(_base=Base())
    values = {structural._MANIFEST_ENV: "/tmp/structural.json"}

    def bound_records(_values, *, asset_class, exact_as_of):
        structural_calls.append((asset_class, exact_as_of))
        return (SimpleNamespace(asset_class=asset_class),)

    monkeypatch.setattr(structural, "load_bound_reference_lane_records", bound_records)

    reference_records = transaction._load_catalog_records(
        core=core,
        values=values,
        policy=object(),
        timestamp=exact,
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
    )
    option_records = transaction._load_catalog_records(
        core=core,
        values=values,
        policy=object(),
        timestamp=exact,
        asset_class=CandidateAssetClass.OPTION,
    )

    assert len(reference_records) == 1
    assert structural_calls == [(CandidateAssetClass.INTERNATIONAL_EQUITY, exact)]
    assert len(option_records) == 1
    assert option_calls == [exact]


def test_bound_structural_failure_never_falls_back_to_reference_reconstruction(monkeypatch) -> None:
    class Base:
        @staticmethod
        def load_comprehensive_market_discovery_config():
            return object()

        @staticmethod
        def scheduled_discovery_lanes(_timestamp):
            return {CandidateAssetClass.INTERNATIONAL_EQUITY}

        _legacy = SimpleNamespace()

    core = SimpleNamespace(_base=Base())
    values = {structural._MANIFEST_ENV: "/tmp/missing-structural.json"}

    def fail_bound(*_args, **_kwargs):
        raise spool.ComprehensiveDiscoverySpoolError("missing structural shard")

    monkeypatch.setattr(structural, "load_bound_reference_lane_records", fail_bound)

    with pytest.raises(spool.ComprehensiveDiscoverySpoolError, match="missing structural shard"):
        transaction._load_catalog_records(
            core=core,
            values=values,
            policy=object(),
            timestamp=_NOW,
            asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        )
