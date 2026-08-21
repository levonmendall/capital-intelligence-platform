from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import _provider_preselection_publication_runtime_core as provider_core
from operations import bounded_lane_comprehensive_discovery_worker as bounded_worker
from operations import bounded_lane_comprehensive_discovery_worker_v2 as bounded_worker_v2
from operations import bounded_provider_preselection_publication as bounded_publication
from operations._bounded_terminal_screening_core import _PublicationSignalSpool
from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord


def _record(symbol: str) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=f"{symbol} test",
        asset_class=CandidateAssetClass.EQUITY,
        economic_exposure="equity",
        venue="XNYS",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="equity",
        provider_kind="eodhd",
        source_identifier=f"test:{symbol}",
        instrument_identifier=f"instrument:{symbol}",
    )


def test_streaming_catalog_fingerprint_matches_canonical() -> None:
    records = (_record("ZZZ"), _record("AAA"), _record("MMM"))
    ordered = bounded_publication._records_for_lane(
        {CandidateAssetClass.EQUITY: records}
    )
    assert bounded_publication._streaming_catalog_fingerprint(ordered) == (
        provider_core._catalog_fingerprint(ordered)
    )


def test_streamed_publication_remains_canonical_screening_input(tmp_path: Path) -> None:
    path = tmp_path / "provider-preselection.json"
    with bounded_publication._SignalStore() as store:
        store.put(
            "AAA",
            {
                "observed_at": "2026-08-21T20:00:00+00:00",
                "eligible": True,
                "source_identifiers": ["provider:test"],
                "factors": {
                    "momentum": {
                        "status": "scored",
                        "score": 0.6,
                        "evidence_identifiers": ["provider:test"],
                    }
                },
            },
        )
        store.add_source("runtime:test")
        store.commit()
        metadata = {
            "schema_version": provider_core.PROVIDER_PRESELECTION_SCHEMA,
            "methodology_version": provider_core._PUBLICATION_METHOD_VERSION,
            "available_at": datetime(2026, 8, 21, 20, tzinfo=timezone.utc).isoformat(),
            "catalog_fingerprint": "abc",
            "catalog_count": 1,
            "signal_count": 1,
            "limitations": [],
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
        bounded_publication._atomic_stream_publication(
            path, metadata=metadata, store=store
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["signal_count"] == 1
    assert tuple(payload["signals"]) == ("AAA",)
    assert payload["source_identifiers"] == ["runtime:test"]
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    with _PublicationSignalSpool(path) as spool:
        assert spool.signal_count == 1
        assert spool.metadata["catalog_count"] == 1
        assert spool.metadata["decision_authority"] is False


def test_screening_worker_does_not_rebuild_overlapping_full_lane_sequences() -> None:
    source = inspect.getsource(bounded_worker._screening_lane_stage)
    assert "eligible = tuple" not in source
    assert "_deduplicate(tuple" not in source
    assert "del catalog_records" in source
    assert "deep_records = continuity" in source
    assert "deep_records.extend(nominated)" in source


def test_v2_publication_worker_uses_bounded_signal_writer() -> None:
    source = inspect.getsource(bounded_worker_v2._publication_lane_stage)
    assert "_publication.ensure_provider_preselection_publication" in source
    assert "core.ensure_provider_preselection_publication" not in source
    assert '"bounded_provider_publication": True' in source


def test_coordinator_routes_every_lane_through_v2_worker() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "operations/lane_local_comprehensive_discovery_coordinator.py").read_text(
        encoding="utf-8"
    )
    assert "bounded_lane_comprehensive_discovery_worker_v2 as _worker" in source
    assert "_worker.run_stage(" in source
    assert '"second_level_lane_memory_bound": True' in source
    assert '"bounded_provider_publication": True' in source


def test_runtime_contract_accepts_active_lane_failure_attribution() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "operations/comprehensive_discovery_runtime_contract.py").read_text(
        encoding="utf-8"
    )
    assert '"bounded_spool_catalog_lane"' in source
    assert '"bounded_spool_publication_lane"' in source
    assert '"bounded_spool_screening_lane"' in source
