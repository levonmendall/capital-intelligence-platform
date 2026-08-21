"""Regressions for bounded reference-directory acquisition and binding."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import generalized_reference_readiness as generalized
from operations import supervised_reference_prequalification as reference


def test_directory_lane_selection_preserves_every_scheduled_eodhd_lane() -> None:
    active_lanes = frozenset(CandidateAssetClass)
    expected = tuple(
        sorted(
            active_lanes & generalized._EODHD_REFERENCE_LANES,
            key=lambda item: item.value,
        )
    )

    assert reference._directory_lanes(active_lanes) == expected
    assert set(reference._directory_lanes(active_lanes)) == (
        active_lanes & generalized._EODHD_REFERENCE_LANES
    )


def test_directory_collection_is_scoped_to_one_lane_per_child() -> None:
    source = inspect.getsource(reference._collect_directory_lane)

    assert "build_eodhd_provider()" in source
    assert "discovery._base._catalog_from_eodhd(" in source
    assert "discovery._catalog_from_eodhd(" not in source
    assert "requested_asset_classes=frozenset({lane})" in source
    assert "store_asset_reference_component(" in source
    assert "_collect_directory_component(" not in source


def test_controller_does_not_rebuild_legacy_directory_aggregate() -> None:
    source = inspect.getsource(reference.prepare_supervised_reference_prequalification)
    loop = source.index("for lane in directory_lanes:")
    run = source.index("_run_component(", loop)
    binding = source.index("component=_BINDING", run)

    assert "_generalized._prime_legacy_components(" not in source
    assert "_legacy._collect_directory_component(" not in source
    assert loop < run < binding


def test_exact_release_binding_runs_behind_fresh_process_boundary() -> None:
    source = inspect.getsource(reference.prepare_supervised_reference_prequalification)
    binding_progress = source.index("active_component=_BINDING")
    binding_run = source.index("_run_component(", binding_progress)
    child_binding = source.index("_bind_release_in_child(", binding_run)

    assert binding_progress < binding_run < child_binding


def test_manifest_transport_is_metadata_only() -> None:
    manifest = SimpleNamespace(
        manifest_id="manifest-1",
        release="release-1",
        captured_at=reference.datetime.now(reference.timezone.utc),
        config_fingerprint="fingerprint-1",
        eodhd_exchanges=("US", "LSE"),
        futures_roots=("ES", "NQ"),
        catalog_counts=(("international_equity", 100), ("future", 13)),
        path=Path("/tmp/reference-manifest.json"),
    )

    payload = reference._manifest_metadata(manifest)

    assert "catalogs" not in payload
    assert "records" not in payload
    assert payload["catalog_counts"] == [
        ["international_equity", 100],
        ["future", 13],
    ]
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_bounded_reference_repair_has_no_investment_or_execution_authority() -> None:
    source = "\n".join(
        (
            inspect.getsource(reference._collect_directory_lane),
            inspect.getsource(reference._collect_futures_lane),
            inspect.getsource(reference._manifest_metadata),
            inspect.getsource(reference._bind_release_in_child),
        )
    ).lower()

    assert "sizing" not in source
    assert "construction" not in source
    assert "order" not in source
    assert "execution" not in source
    assert "real_money_authorized" in source
