from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from operations import comprehensive_discovery_memory_attribution as attribution
from scripts import enrich_stage_isolated_prequalification_telemetry as enrichment


def test_memory_attribution_uses_watchdog_updated_at() -> None:
    observed_at = datetime(2026, 8, 22, 1, 15, tzinfo=timezone.utc)
    observed = SimpleNamespace(
        component="bounded-spool-publication-lane:crypto",
        updated_at=observed_at,
        metrics={"active_lane_index": 7, "candidate_lanes": 13},
    )

    context = attribution._context_from_progress(observed)

    assert context is not None
    assert context["progress_kind"] == "active"
    assert context["substage"] == "publication-lane"
    assert context["asset_class"] == "crypto"
    assert context["active_lane_index"] == 7
    assert context["recorded_at"] == observed_at.isoformat()
    assert context["paper_only"] is True
    assert context["real_money_authorized"] is False
    assert context["execution_authority"] is False


def test_current_active_marker_survives_reused_request_mtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from operations import comprehensive_discovery_input_spool as spool
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import lane_local_watchdog_progress as lane_progress

    request_path = tmp_path / "epoch" / "request" / "request.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text("{}\n", encoding="utf-8")

    boundary = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
    active_at = boundary + timedelta(minutes=4)
    old_request_time = (boundary - timedelta(hours=2)).timestamp()
    request_path.touch()
    import os

    os.utime(request_path, (old_request_time, old_request_time))

    lanes = tuple(
        SimpleNamespace(value=name)
        for name in (
            "us_equity",
            "us_etf",
            "cash_equivalent",
            "fixed_income",
            "international_equity",
            "commodity",
            "fx",
            "crypto",
            "real_estate",
            "future",
            "option",
            "volatility",
            "alternative",
        )
    )

    monkeypatch.setattr(spool, "_root", lambda values: tmp_path)
    monkeypatch.setattr(spool, "_release", lambda values: "release-716")
    monkeypatch.setattr(lane_local, "_candidate_lanes", lambda: lanes)
    monkeypatch.setattr(
        lane_progress,
        "_load_request_identity",
        lambda path, module: {
            "request_id": "request-716",
            "release": "release-716",
        },
    )
    monkeypatch.setattr(
        lane_progress,
        "_load_active_state",
        lambda path, *, request_id, release, boundary: (
            "publication-lane",
            "crypto",
            7,
            active_at,
        ),
    )

    context = attribution._current_active_marker_context(
        {"CAPITAL_INTELLIGENCE_RELEASE": "release-716"},
        boundary=boundary,
    )

    assert context is not None
    assert context["component"] == "bounded-spool-publication-lane:crypto"
    assert context["progress_kind"] == "active"
    assert context["asset_class"] == "crypto"
    assert context["active_lane_index"] == 7
    assert context["recorded_at"] == active_at.isoformat()


def _public_resource_payload() -> dict[str, object]:
    return {
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "active_release": "release-716",
        "prequalification_failure_context": {
            "credential_safe": True,
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
            "failure_progress_kind": "active",
            "failure_substage": "publication-lane",
            "failure_asset_class": "crypto",
            "failure_component": "bounded-spool-publication-lane:crypto",
            "failure_lane_index": 7,
            "memory_trigger_reason": "working_set",
            "memory_accounting_source": "cgroup_v2",
            "memory_reclaim_attempted": True,
            "memory_reclaim_supported": True,
            "memory_reclaim_effective": False,
            "memory_reclaim_ever_effective": True,
            "memory_reclaim_error_type": "IneffectiveReclaim",
            "memory_reclaim_requested_kib": 108376,
            "memory_reclaim_raw_before_kib": 1963044,
            "memory_reclaim_raw_after_kib": 1900000,
            "memory_reclaim_working_set_before_kib": 646572,
            "memory_reclaim_working_set_after_kib": 650000,
            "memory_reclaim_reclaimed_kib": 63044,
            "memory_reclaim_attempt_count": 3,
            "memory_reclaim_success_count": 1,
            "memory_reclaim_max_attempts": 3,
            "ignored_field": "must-not-copy",
        },
        "progress_metrics": {
            "failure_lane_index": 7,
            "failure_progress_active": 1,
            "memory_trigger_working_set": 1,
            "memory_process_peak_rss_kib": 1380000,
            "memory_working_set_peak_kib": 1441000,
            "memory_working_set_boundary_kib": 1441792,
            "lane_active_lane_index": 7,
            "lane_candidate_lanes": 13,
            "unknown_metric": 999,
        },
    }


def test_final_telemetry_enrichment_preserves_only_safe_resource_context() -> None:
    snapshot = {
        "diagnostic": {
            "release_matches_expected": True,
            "progress_metrics": {},
        }
    }

    enriched = enrichment.enrich_snapshot(
        snapshot,
        _public_resource_payload(),
        expected_release="release-716",
    )

    diagnostic = enriched["diagnostic"]
    context = diagnostic["prequalification_resource_failure_context"]
    metrics = diagnostic["progress_metrics"]
    assert context["failure_progress_kind"] == "active"
    assert context["failure_substage"] == "publication-lane"
    assert context["failure_asset_class"] == "crypto"
    assert context["failure_lane_index"] == 7
    assert context["memory_reclaim_attempted"] is True
    assert context["memory_reclaim_supported"] is True
    assert context["memory_reclaim_effective"] is False
    assert context["memory_reclaim_ever_effective"] is True
    assert context["memory_reclaim_error_type"] == "IneffectiveReclaim"
    assert context["memory_reclaim_requested_kib"] == 108376
    assert context["memory_reclaim_raw_before_kib"] == 1963044
    assert context["memory_reclaim_raw_after_kib"] == 1900000
    assert context["memory_reclaim_working_set_before_kib"] == 646572
    assert context["memory_reclaim_working_set_after_kib"] == 650000
    assert context["memory_reclaim_reclaimed_kib"] == 63044
    assert context["memory_reclaim_attempt_count"] == 3
    assert context["memory_reclaim_success_count"] == 1
    assert context["memory_reclaim_max_attempts"] == 3
    assert "ignored_field" not in context
    assert diagnostic["prequalification_failure_asset_class"] == "crypto"
    assert diagnostic["prequalification_failure_lane_index"] == 7
    assert metrics["memory_process_peak_rss_kib"] == 1380000
    assert metrics["memory_working_set_boundary_kib"] == 1441792
    assert metrics["lane_active_lane_index"] == 7
    assert "unknown_metric" not in metrics
    assert enriched["enriched_from_resource_failure_context"] is True


def test_resource_context_requires_explicit_non_authority() -> None:
    payload = _public_resource_payload()
    payload["prequalification_failure_context"]["execution_authority"] = True
    snapshot = {
        "diagnostic": {
            "release_matches_expected": True,
            "progress_metrics": {},
        }
    }

    enriched = enrichment.enrich_snapshot(
        snapshot,
        payload,
        expected_release="release-716",
    )

    diagnostic = enriched["diagnostic"]
    assert "prequalification_resource_failure_context" not in diagnostic
    assert diagnostic["progress_metrics"]["memory_trigger_working_set"] == 1


def test_render_reclaim_outcomes_remain_distinguishable() -> None:
    cases = (
        (False, False, "UnsupportedCgroupReclaim"),
        (True, False, None),
        (True, True, None),
    )
    observed = []
    for supported, effective, error_type in cases:
        payload = _public_resource_payload()
        context = payload["prequalification_failure_context"]
        context["memory_reclaim_supported"] = supported
        context["memory_reclaim_effective"] = effective
        context["memory_reclaim_error_type"] = error_type
        enriched = enrichment.enrich_snapshot(
            {"diagnostic": {"release_matches_expected": True, "progress_metrics": {}}},
            payload,
            expected_release="release-716",
        )
        terminal = enriched["diagnostic"]["prequalification_resource_failure_context"]
        observed.append(
            (
                terminal["memory_reclaim_supported"],
                terminal["memory_reclaim_effective"],
                terminal.get("memory_reclaim_error_type"),
            )
        )

    assert observed == list(cases)
