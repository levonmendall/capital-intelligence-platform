"""Tests for the mandatory commodity prerequisite before paper execution."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance.commodity_readiness import (
    CommodityReadinessError,
    evaluate_commodity_readiness,
    load_commodity_scope,
    require_commodity_readiness_report,
    write_commodity_readiness_report,
)


UTC = timezone.utc
NOW = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
PUBLICATION = "eligible-universe:commodity-baseline.1"


def _benchmark(identifier: str) -> dict[str, object]:
    return {
        "identifier": identifier,
        "observed_at": (NOW - timedelta(minutes=10)).isoformat(),
        "available_at": (NOW - timedelta(minutes=9)).isoformat(),
        "retrieved_at": (NOW - timedelta(minutes=8)).isoformat(),
        "history_years": 15,
        "licensed_use_approved": True,
        "point_in_time_supported": True,
        "market_price_ready": True,
        "forward_curve_ready": True,
        "history_ready": True,
        "source_identifier": f"source:commodity:{identifier}",
        "market_data_certification_identifier": f"cert:price:{identifier}",
        "curve_certification_identifier": f"cert:curve:{identifier}",
    }


def _proxy(category: str, symbol: str) -> dict[str, object]:
    return {
        "category": category,
        "instrument_identifier": f"instrument:us-etf:{symbol.lower()}",
        "symbol": symbol,
        "asset_class": "us_etf",
        "country_code": "US",
        "venue": "NYSEARCA",
        "currency": "USD",
        "eligible_universe_publication_identifier": PUBLICATION,
        "in_eligible_universe": True,
        "paper_eligible": True,
        "unlevered": True,
        "inverse": False,
        "direct_derivative": False,
        "liquidity_ready": True,
        "execution_inputs_ready": True,
        "cost_model_ready": True,
        "market_data_certification_identifier": f"cert:market:{symbol}",
        "execution_certification_identifier": f"cert:execution:{symbol}",
        "source_identifiers": [f"source:proxy:{symbol}"],
    }


def _evidence() -> dict[str, object]:
    scope = load_commodity_scope()
    symbols = {
        "gold": "IAU",
        "silver": "SIVR",
        "oil_energy": "USO",
        "industrial_metals": "CPER",
        "agriculture": "DBA",
        "broad_commodity": "PDBC",
    }
    return {
        "schema_version": "commodity-paper-test-evidence.v1",
        "identifier": "commodity-evidence:test-ready",
        "as_of": NOW.isoformat(),
        "knowledge_cutoff": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=24)).isoformat(),
        "baseline_identifier": "test-baseline:commodity.1",
        "process_version": "capital-intelligence-investment-process.v1",
        "code_version": "commit:test",
        "eligible_universe_publication_identifier": PUBLICATION,
        "direct_derivatives_authorized": False,
        "benchmarks": [
            _benchmark(item.identifier) for item in scope.required_benchmarks
        ],
        "proxies": [
            _proxy(item.category, symbols[item.category])
            for item in scope.required_proxy_categories
        ],
    }


def test_complete_commodity_scope_is_ready_and_bound_to_universe(tmp_path: Path) -> None:
    report = evaluate_commodity_readiness(
        scope=load_commodity_scope(),
        evidence=_evidence(),
    )
    assert report["ready"] is True
    assert report["blockers"] == []
    assert report["direct_derivatives_authorized"] is False
    assert all(item["ready"] for item in report["benchmark_coverage"])
    assert all(item["ready"] for item in report["proxy_coverage"])

    path = tmp_path / "commodity-readiness.json"
    write_commodity_readiness_report(report, path)
    loaded = require_commodity_readiness_report(
        path,
        as_of=NOW + timedelta(minutes=1),
        eligible_universe_publication_identifier=PUBLICATION,
    )
    assert loaded["content_hash"] == report["content_hash"]


def test_missing_benchmark_and_proxy_block_readiness() -> None:
    evidence = _evidence()
    evidence["benchmarks"] = evidence["benchmarks"][1:]
    evidence["proxies"] = [
        item for item in evidence["proxies"] if item["category"] != "gold"
    ]
    report = evaluate_commodity_readiness(
        scope=load_commodity_scope(),
        evidence=evidence,
    )
    assert report["ready"] is False
    detail = " ".join(report["blockers"])
    assert "benchmark:gold" in detail
    assert "proxy:gold" in detail


def test_leveraged_inverse_or_direct_derivative_proxy_is_rejected() -> None:
    evidence = _evidence()
    evidence["proxies"][0]["unlevered"] = False
    evidence["proxies"][0]["inverse"] = True
    evidence["proxies"][0]["direct_derivative"] = True
    report = evaluate_commodity_readiness(
        scope=load_commodity_scope(),
        evidence=evidence,
    )
    assert report["ready"] is False
    assert any("proxy:gold" in item for item in report["blockers"])


def test_tampered_or_wrong_universe_report_cannot_authorize_execution(
    tmp_path: Path,
) -> None:
    report = evaluate_commodity_readiness(
        scope=load_commodity_scope(),
        evidence=_evidence(),
    )
    path = tmp_path / "commodity-readiness.json"
    write_commodity_readiness_report(report, path)

    with pytest.raises(CommodityReadinessError, match="construction universe"):
        require_commodity_readiness_report(
            path,
            as_of=NOW + timedelta(minutes=1),
            eligible_universe_publication_identifier="eligible-universe:other",
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ready"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CommodityReadinessError, match="hash is invalid"):
        require_commodity_readiness_report(
            path,
            as_of=NOW + timedelta(minutes=1),
            eligible_universe_publication_identifier=PUBLICATION,
        )
