from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance import (
    DecisionInformationCoverageRequirement,
    DecisionInformationDomain,
    DecisionInformationReadinessState,
    DecisionInformationSourceCapability,
    DecisionInformationSourceRole,
    MaximumDecisionInformationManifest,
    MaximumDecisionInformationReadinessEvaluator,
    load_maximum_decision_information_manifest,
)
from run_decision_information_readiness import main

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "maximum_decision_information_scope.json"
SCHEMA = ROOT / "schemas" / "maximum_decision_information_scope.schema.json"


def _source(identifier: str, group: str) -> DecisionInformationSourceCapability:
    return DecisionInformationSourceCapability(
        identifier=identifier,
        source_name=identifier,
        role=DecisionInformationSourceRole.PRIMARY,
        independence_group=group,
        enabled=True,
        domains=(DecisionInformationDomain.CURRENT_EVENTS_NEWS,),
        authoritative_domains=(),
        credential_environment_variables=(f"{identifier.upper().replace('-', '_')}_KEY",),
        usage_rights_approved=True,
        storage_and_backup_approved=True,
        derived_analytics_approved=True,
        internal_display_approved=True,
        paper_simulation_approved=True,
        event_time_supported=True,
        publication_time_supported=True,
        availability_time_supported=True,
        correction_history_supported=True,
        historical_coverage_supported=True,
        provenance_complete=True,
        entity_mapping_supported=True,
        geographic_mapping_supported=True,
        reliability_policy_defined=True,
        manipulation_controls_defined=True,
        deduplication_supported=True,
        service_level_defined=True,
        certification_required=True,
        certification_identifier=f"certification:{identifier}:v1",
    )


def _manifest(*sources: DecisionInformationSourceCapability) -> MaximumDecisionInformationManifest:
    return MaximumDecisionInformationManifest(
        identifier="maximum-information:test",
        schema_version="maximum-decision-information-manifest.v1",
        objective="Test independently corroborated current events.",
        require_complete_scope=False,
        sources=tuple(sources),
        requirements=(
            DecisionInformationCoverageRequirement(
                domain=DecisionInformationDomain.CURRENT_EVENTS_NEWS,
                source_identifiers=tuple(item.identifier for item in sources),
                minimum_ready_sources=len(sources),
                minimum_independence_groups=len(sources),
                authoritative_required=False,
                rationale="Require every fixture source.",
            ),
        ),
    )


def test_default_manifest_matches_schema_and_declares_maximum_scope() -> None:
    import jsonschema

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8"))
    ).validate(payload)
    manifest = load_maximum_decision_information_manifest(MANIFEST)

    assert manifest.require_complete_scope is True
    assert {item.domain for item in manifest.requirements} == set(
        DecisionInformationDomain
    )
    assert len(manifest.requirements) == 28


def test_default_scope_fails_closed_until_sources_are_licensed_and_certified() -> None:
    report = MaximumDecisionInformationReadinessEvaluator().evaluate(
        load_maximum_decision_information_manifest(MANIFEST),
        environment={"SEC_USER_AGENT": "Capital Intelligence test@example.com"},
    )

    assert report.state is DecisionInformationReadinessState.BLOCKED
    assert report.maximum_scope_declared is True
    assert report.all_domains_ready is False
    assert report.current_events_and_news_ready is False
    assert "CAPITAL_INTELLIGENCE_GLOBAL_NEWS_API_KEY" in (
        report.missing_environment_variables
    )
    assert report.real_money_authorized is False


def test_three_ready_independent_sources_can_satisfy_current_events() -> None:
    sources = (
        _source("official-source", "official"),
        _source("licensed-newswire", "newswire"),
        _source("independent-journalism", "journalism"),
    )
    environment = {
        variable: "configured"
        for source in sources
        for variable in source.credential_environment_variables
    }
    report = MaximumDecisionInformationReadinessEvaluator().evaluate(
        _manifest(*sources),
        environment=environment,
    )

    assert report.state is DecisionInformationReadinessState.READY
    assert report.current_events_and_news_ready is True
    assert report.all_domains_ready is True
    assert report.blockers == ()


def test_syndicated_sources_do_not_count_as_independent() -> None:
    sources = (
        _source("news-copy-a", "same-syndication-chain"),
        _source("news-copy-b", "same-syndication-chain"),
    )
    environment = {
        variable: "configured"
        for source in sources
        for variable in source.credential_environment_variables
    }
    report = MaximumDecisionInformationReadinessEvaluator().evaluate(
        _manifest(*sources),
        environment=environment,
    )

    assert report.all_domains_ready is False
    assessment = report.domains[0]
    assert assessment.ready_source_identifiers == (
        "news-copy-a",
        "news-copy-b",
    )
    assert assessment.ready_independence_groups == ("same-syndication-chain",)
    assert any("independent source group" in item for item in assessment.blockers)


def test_missing_license_or_point_in_time_support_blocks_source() -> None:
    ready = _source("source", "group")
    invalid = DecisionInformationSourceCapability(
        **{
            **{
                field: getattr(ready, field)
                for field in ready.__dataclass_fields__
            },
            "usage_rights_approved": False,
            "availability_time_supported": False,
        }
    )
    deficiencies = invalid.deficiencies(
        {invalid.credential_environment_variables[0]: "configured"},
        domain=DecisionInformationDomain.CURRENT_EVENTS_NEWS,
        authoritative_required=False,
    )

    assert "usage rights not approved" in deficiencies
    assert "availability-time support not approved" in deficiencies


def test_cli_reports_scope_without_disclosing_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(("--manifest", str(MANIFEST), "--compact"))
    payload = json.loads(capsys.readouterr().out)

    assert result == 3
    assert payload["state"] == "blocked"
    assert payload["maximum_scope_declared"] is True
    assert payload["current_events_and_news_ready"] is False
    assert "secret_values" not in payload


def test_cli_lists_configuration_names_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        (
            "--manifest",
            str(MANIFEST),
            "--show-required-environment",
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert "CAPITAL_INTELLIGENCE_GLOBAL_NEWS_API_KEY" in (
        payload["required_environment_variables"]
    )
    assert payload["secret_values_disclosed"] is False
