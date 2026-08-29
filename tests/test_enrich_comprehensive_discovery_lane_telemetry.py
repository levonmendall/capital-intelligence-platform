from scripts import enrich_comprehensive_discovery_telemetry as telemetry


EXPECTED_RELEASE = "release-lane-timing"


def _snapshot() -> dict[str, object]:
    return {
        "diagnostic": {
            "active_release": EXPECTED_RELEASE,
            "stage": "evidence_refresh",
            "state": "prequalifying",
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _lane_telemetry(*, release: str = EXPECTED_RELEASE) -> dict[str, object]:
    return {
        "schema_version": "comprehensive-discovery-lane-telemetry.v1",
        "request_id": "request-123",
        "release": release,
        "decision_epoch": "2026-08-29T00:42:14.824293+00:00",
        "updated_at": "2026-08-29T00:49:00+00:00",
        "structural_cache_hits": 1,
        "structural_cache_misses": 0,
        "structural_cache_unknown": 0,
        "slowest_completed_phase": {
            "asset_class": "international_equity",
            "phase": "screening",
            "seconds": 81.25,
        },
        "lanes": [
            {
                "asset_class": "international_equity",
                "index": 0,
                "structural_cache_hit": True,
                "structural_elapsed_seconds": 1.5,
                "publication_elapsed_seconds": 12.25,
                "screening_elapsed_seconds": 81.25,
                "total_elapsed_seconds": 95.0,
                "post_hit_elapsed_seconds": 93.5,
            }
        ],
        "credential_safe": True,
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "watchdog_progress_authority": False,
    }


def _public_payload(*, lane_telemetry: object) -> dict[str, object]:
    return {
        "active_release": EXPECTED_RELEASE,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        # Deliberately omit the legacy deep-node/finalizer detail. This is the exact
        # production shape that previously caused enrichment to return before copying
        # the new per-lane timing envelope.
        "detail": "",
        "comprehensive_discovery_lane_telemetry": lane_telemetry,
    }


def test_lane_telemetry_survives_without_legacy_discovery_progress():
    enriched = telemetry.enrich_snapshot(
        _snapshot(),
        _public_payload(lane_telemetry=_lane_telemetry()),
        expected_release=EXPECTED_RELEASE,
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    lane = diagnostic["comprehensive_discovery_lane_telemetry"]
    assert lane["release"] == EXPECTED_RELEASE
    assert lane["structural_cache_hits"] == 1
    assert lane["lanes"][0]["structural_cache_hit"] is True
    assert lane["lanes"][0]["screening_elapsed_seconds"] == 81.25
    assert lane["watchdog_progress_authority"] is False
    assert lane["real_money_authorized"] is False
    assert "comprehensive_discovery_progress" not in diagnostic
    assert enriched["enriched_from_comprehensive_discovery_lane_telemetry"] is True


def test_lane_telemetry_requires_exact_release_identity():
    enriched = telemetry.enrich_snapshot(
        _snapshot(),
        _public_payload(lane_telemetry=_lane_telemetry(release="older-release")),
        expected_release=EXPECTED_RELEASE,
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert "comprehensive_discovery_lane_telemetry" not in diagnostic
    assert "enriched_from_comprehensive_discovery_lane_telemetry" not in enriched


def test_lane_telemetry_cannot_claim_evidence_or_execution_authority():
    unsafe_lane = _lane_telemetry()
    unsafe_lane["evidence_certified"] = True

    enriched = telemetry.enrich_snapshot(
        _snapshot(),
        _public_payload(lane_telemetry=unsafe_lane),
        expected_release=EXPECTED_RELEASE,
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert "comprehensive_discovery_lane_telemetry" not in diagnostic
    assert "enriched_from_comprehensive_discovery_lane_telemetry" not in enriched


def test_legacy_failure_progress_still_enriches_with_lane_telemetry():
    public_payload = _public_payload(lane_telemetry=_lane_telemetry())
    public_payload["detail"] = (
        "node=deep-market-evidence:international_equity "
        "asset_class=international_equity failure_type=TimeoutError "
        "completed_nodes=3 required_nodes=8"
    )

    enriched = telemetry.enrich_snapshot(
        _snapshot(),
        public_payload,
        expected_release=EXPECTED_RELEASE,
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["comprehensive_discovery_lane_telemetry"]["release"] == EXPECTED_RELEASE
    assert diagnostic["comprehensive_discovery_progress"]["blocking_unit"] == (
        "deep-market-evidence:international_equity"
    )
    assert diagnostic["prequalification_failure_reason"] == "discovery_lane_failure"
    assert enriched["enriched_from_comprehensive_discovery"] is True
