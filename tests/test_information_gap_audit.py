from __future__ import annotations

import json

from operations.information_gap_audit import build_information_gap_audit


def test_information_gap_audit_distinguishes_static_implementation_from_runtime_certification(tmp_path) -> None:
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "identifier": "scope:test",
                "sources": [],
                "requirements": [{"domain": "government_policy_regulation"}],
            }
        ),
        encoding="utf-8",
    )
    catalog = tmp_path / "public_live_information_sources.json"
    catalog.write_text(
        json.dumps(
            {
                "identifier": "catalog:test",
                "sources": [
                    {
                        "identifier": "official-policy",
                        "source_name": "Official Policy",
                        "parser": "rss_atom",
                        "endpoint": "https://example.com/feed",
                        "source_type": "official",
                        "independence_group": "official-policy",
                        "enabled": True,
                        "required": False,
                        "credential_environment_variables": [],
                        "parameters": {},
                        "headers": {},
                        "maximum_records": 10,
                        "domains": ["government_policy_regulation"],
                        "impact_channels": ["policy"],
                        "reliability": 0.99,
                        "relevance": 0.90,
                        "materiality": 0.80,
                        "license_identifier": "public",
                        "usage_rights_identifier": "internal",
                        "limitations": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = build_information_gap_audit(
        scope_path=scope,
        public_catalog_path=catalog,
    )
    assert report["decision_gap_count"] == 1
    assert report["domain_status"][0]["monitored"] is True
    assert report["domain_status"][0]["decision_certified_and_healthy"] is False

    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "sources": [
                    {"source_identifier": "official-policy", "succeeded": True}
                ]
            }
        ),
        encoding="utf-8",
    )
    report = build_information_gap_audit(
        scope_path=scope,
        public_catalog_path=catalog,
        runtime_report_path=runtime,
    )
    assert report["decision_gap_count"] == 0
    assert report["domain_status"][0]["decision_certified_and_healthy"] is True
    assert report["investment_authority"] is False
