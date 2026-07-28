from __future__ import annotations

import json
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from governance import (
    AllMarketsDataManifest,
    AllMarketsDataReadinessEvaluator,
    AllMarketsDataReadinessState,
    DataDomain,
    DataProviderRole,
    DatasetCoverageRequirement,
    MarketDataScope,
    MarketDataScopeState,
    ProviderDataCapability,
    load_data_readiness_manifest,
)
from run_data_readiness import main


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "all_markets_data_readiness.json"


def _provider(
    *,
    enabled: bool = True,
    authoritative_domains: tuple[DataDomain, ...] | None = None,
    credential_environment_variables: tuple[str, ...] = ("TEST_DATA_KEY",),
) -> ProviderDataCapability:
    domains = (
        DataDomain.SECURITY_MASTER,
        DataDomain.MARKET_PRICES,
        DataDomain.QUOTES_LIQUIDITY,
        DataDomain.MARKET_CALENDARS,
        DataDomain.EXECUTION_INPUTS,
    )
    return ProviderDataCapability(
        identifier="provider:ready",
        provider_name="Ready Provider",
        role=DataProviderRole.PRIMARY,
        enabled=enabled,
        domains=domains,
        authoritative_domains=(
            domains if authoritative_domains is None else authoritative_domains
        ),
        credential_environment_variables=credential_environment_variables,
        usage_rights_approved=True,
        point_in_time_supported=True,
        historical_coverage_supported=True,
        provenance_complete=True,
        service_level_defined=True,
        storage_and_backup_approved=True,
        derived_analytics_approved=True,
        paper_simulation_approved=True,
        certification_required=True,
        certification_identifier="certification:ready-provider:v1",
    )


def _complete_manifest(provider: ProviderDataCapability) -> AllMarketsDataManifest:
    required_domains = (
        DataDomain.SECURITY_MASTER,
        DataDomain.MARKET_PRICES,
        DataDomain.QUOTES_LIQUIDITY,
        DataDomain.MARKET_CALENDARS,
        DataDomain.EXECUTION_INPUTS,
    )
    markets = [
        MarketDataScope(
            asset_class=CandidateAssetClass.US_EQUITY,
            state=MarketDataScopeState.PAPER_ELIGIBLE,
            requirements=tuple(
                DatasetCoverageRequirement(
                    domain=domain,
                    provider_identifiers=(provider.identifier,),
                )
                for domain in required_domains
            ),
            rationale="Controlled paper-test market.",
        )
    ]
    markets.extend(
        MarketDataScope(
            asset_class=asset_class,
            state=MarketDataScopeState.PROHIBITED,
            requirements=(),
            rationale="Not part of this minimal fixture.",
        )
        for asset_class in CandidateAssetClass
        if asset_class is not CandidateAssetClass.US_EQUITY
    )
    return AllMarketsDataManifest(
        identifier="all-markets:test-ready",
        schema_version="all-markets-data-manifest.v1",
        reporting_currency="USD",
        require_complete_candidate_scope=True,
        providers=(provider,),
        markets=tuple(markets),
    )


def test_governance_and_cio_packages_import_without_order_dependency() -> None:
    import governance
    import cio

    assert governance.MarketDataScopeState.EVIDENCE_ONLY.value == "evidence_only"
    assert cio.RecommendationUniversePolicy.__name__ == "RecommendationUniversePolicy"



def test_default_manifest_matches_published_json_schema() -> None:
    import jsonschema

    manifest_payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    schema_payload = json.loads(
        (ROOT / "schemas" / "all_markets_data_readiness.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.Draft202012Validator(schema_payload).validate(manifest_payload)

def test_default_manifest_declares_every_candidate_market() -> None:
    manifest = load_data_readiness_manifest(DEFAULT_MANIFEST)

    assert {item.asset_class for item in manifest.markets} == set(
        CandidateAssetClass
    )
    states = {item.asset_class: item.state for item in manifest.markets}
    assert states[CandidateAssetClass.US_EQUITY] is MarketDataScopeState.PAPER_ELIGIBLE
    for asset_class in set(CandidateAssetClass) - {CandidateAssetClass.OTHER}:
        assert states[asset_class] is MarketDataScopeState.PAPER_ELIGIBLE
    assert states[CandidateAssetClass.OTHER] is MarketDataScopeState.PROHIBITED




def test_derivative_markets_require_contract_margin_and_surface_data() -> None:
    manifest = load_data_readiness_manifest(DEFAULT_MANIFEST)
    requirements = {
        item.asset_class: {requirement.domain for requirement in item.requirements}
        for item in manifest.markets
    }

    assert {
        DataDomain.DERIVATIVE_CONTRACTS,
        DataDomain.MARGIN_COLLATERAL,
    } <= requirements[CandidateAssetClass.FUTURE]
    for asset_class in (CandidateAssetClass.OPTION, CandidateAssetClass.VOLATILITY):
        assert {
            DataDomain.DERIVATIVE_CONTRACTS,
            DataDomain.MARGIN_COLLATERAL,
            DataDomain.VOLATILITY_SURFACES,
        } <= requirements[asset_class]

    provider = next(
        item
        for item in manifest.providers
        if item.identifier == "commercial-global-market-data"
    )
    assert {
        DataDomain.DERIVATIVE_CONTRACTS,
        DataDomain.MARGIN_COLLATERAL,
        DataDomain.VOLATILITY_SURFACES,
    } <= set(provider.authoritative_domains)


def test_default_manifest_fails_closed_until_external_providers_are_onboarded() -> None:
    manifest = load_data_readiness_manifest(DEFAULT_MANIFEST)
    report = AllMarketsDataReadinessEvaluator().evaluate(
        manifest,
        environment={},
    )

    assert report.state is AllMarketsDataReadinessState.BLOCKED
    assert report.global_test_data_ready is False
    assert "FRED_API_KEY" in report.missing_environment_variables
    assert "SEC_USER_AGENT" in report.missing_environment_variables
    assert "CAPITAL_INTELLIGENCE_GLOBAL_MARKET_DATA_API_KEY" in (
        report.missing_environment_variables
    )
    assert report.real_money_authorized is False


def test_sec_current_reference_feed_cannot_satisfy_authoritative_security_master() -> None:
    manifest = load_data_readiness_manifest(DEFAULT_MANIFEST)
    sec = next(
        item for item in manifest.providers if item.identifier == "official-sec-edgar"
    )

    deficiencies = sec.deficiencies(
        {"SEC_USER_AGENT": "Capital Intelligence test@example.com"},
        domain=DataDomain.SECURITY_MASTER,
        paper_use=False,
        authoritative_required=True,
    )

    assert "is not authoritative for security_master" in deficiencies


def test_complete_certified_provider_can_satisfy_a_minimal_global_manifest() -> None:
    provider = _provider()
    report = AllMarketsDataReadinessEvaluator().evaluate(
        _complete_manifest(provider),
        environment={"TEST_DATA_KEY": "configured"},
    )

    assert report.state is AllMarketsDataReadinessState.READY
    assert report.global_test_data_ready is True
    assert report.paper_eligible_data_ready is True
    assert report.blockers == ()


def test_disabled_or_non_authoritative_provider_never_counts_as_ready() -> None:
    disabled = _provider(enabled=False)
    disabled_report = AllMarketsDataReadinessEvaluator().evaluate(
        _complete_manifest(disabled),
        environment={"TEST_DATA_KEY": "configured"},
    )
    assert disabled_report.global_test_data_ready is False

    non_authoritative = _provider(authoritative_domains=())
    non_authoritative_report = AllMarketsDataReadinessEvaluator().evaluate(
        _complete_manifest(non_authoritative),
        environment={"TEST_DATA_KEY": "configured"},
    )
    assert non_authoritative_report.global_test_data_ready is False


def test_paper_eligible_market_requires_execution_grade_domains() -> None:
    with pytest.raises(ValueError, match="missing required domains"):
        MarketDataScope(
            asset_class=CandidateAssetClass.US_EQUITY,
            state=MarketDataScopeState.PAPER_ELIGIBLE,
            requirements=(
                DatasetCoverageRequirement(
                    domain=DataDomain.MARKET_PRICES,
                    provider_identifiers=("provider:ready",),
                ),
            ),
            rationale="Incomplete fixture.",
        )


def test_cli_emits_one_safe_json_document_and_nonzero_when_blocked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        (
            "--manifest",
            str(DEFAULT_MANIFEST),
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["state"] == "blocked"
    assert payload["global_test_data_ready"] is False
    assert "secret" not in json.dumps(payload).lower()


def test_cli_lists_required_variable_names_without_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        (
            "--manifest",
            str(DEFAULT_MANIFEST),
            "--show-required-environment",
            "--compact",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert "FRED_API_KEY" in payload["required_environment_variables"]
    assert "CAPITAL_INTELLIGENCE_CRYPTO_VALIDATION_API_KEY" in (
        payload["required_environment_variables"]
    )
    assert payload["secret_values_disclosed"] is False


def test_ready_report_can_generate_existing_certified_data_gate() -> None:
    from datetime import datetime, timedelta, timezone
    from governance import ReadinessGate, ReadinessGateState

    provider = _provider()
    report = AllMarketsDataReadinessEvaluator().evaluate(
        _complete_manifest(provider),
        environment={"TEST_DATA_KEY": "configured"},
    )
    certified_at = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
    certification = report.to_readiness_gate_certification(
        identifier="gate:certified-data:test",
        certified_at=certified_at,
        effective_at=certified_at,
        expires_at=certified_at + timedelta(days=30),
        baseline_identifier="baseline:test",
        process_version="process:test",
        code_version="commit:test",
        authority_identifiers=("authority:data-governance",),
    )

    assert certification.gate is ReadinessGate.CERTIFIED_DATA
    assert certification.state is ReadinessGateState.SATISFIED
    assert report.evidence_identifier in certification.evidence_identifiers
    assert certification.authority_identifiers == ("authority:data-governance",)


def test_blocked_report_cannot_generate_certified_data_gate() -> None:
    from datetime import datetime, timedelta, timezone
    from governance import DataReadinessError

    report = AllMarketsDataReadinessEvaluator().evaluate(
        load_data_readiness_manifest(DEFAULT_MANIFEST),
        environment={},
    )
    certified_at = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
    with pytest.raises(DataReadinessError, match="cannot certify"):
        report.to_readiness_gate_certification(
            identifier="gate:blocked",
            certified_at=certified_at,
            effective_at=certified_at,
            expires_at=certified_at + timedelta(days=30),
            baseline_identifier="baseline:test",
            process_version="process:test",
            code_version="commit:test",
            authority_identifiers=("authority:data-governance",),
        )


def test_governance_api_exposes_redacted_all_markets_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.routes.governance import data_readiness

    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_DATA_READINESS_MANIFEST",
        str(DEFAULT_MANIFEST),
    )
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    payload = data_readiness()

    assert payload["state"] == "blocked"
    assert payload["global_test_data_ready"] is False
    assert "FRED_API_KEY" in payload["missing_environment_variables"]
    assert "secret_values" not in payload
