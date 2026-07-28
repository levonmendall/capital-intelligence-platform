from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from data.derivative_market import DerivativeDataCertificationReport

from governance import (
    SQLiteAssetClassApprovalStore,
    SQLiteDecisionInformationActivationStore,
    load_data_readiness_manifest,
    load_maximum_decision_information_manifest,
)
from governance.data_readiness import DataDomain
from governance.provider_activation import SQLiteProviderActivationStore
from operations.all_markets_paper_rehearsal import (
    run_all_markets_paper_rehearsal,
)
from operations.paper_market_readiness import (
    DATA_DOMAIN_DATASET_TYPE,
    assess_universal_paper_market_readiness,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)


def test_provider_neutral_dataset_contract_covers_every_readiness_domain() -> None:
    assert set(DATA_DOMAIN_DATASET_TYPE) == set(DataDomain)


def test_repository_is_internally_ready_while_external_activation_fails_closed(
    tmp_path: Path,
) -> None:
    report = assess_universal_paper_market_readiness(
        manifest=load_data_readiness_manifest(
            "config/all_markets_data_readiness.json"
        ),
        information_manifest=load_maximum_decision_information_manifest(
            "config/maximum_decision_information_scope.json"
        ),
        evaluated_at=AS_OF,
        environment={},
        provider_activation_store=SQLiteProviderActivationStore(
            tmp_path / "providers.db"
        ),
        decision_information_activation_store=(
            SQLiteDecisionInformationActivationStore(
                tmp_path / "information.db"
            )
        ),
        asset_class_approval_store=SQLiteAssetClassApprovalStore(
            tmp_path / "assets.db"
        ),
    )

    assert report.internal_ready is True
    assert report.paper_ready is False
    assert report.market_data_ready is False
    assert report.decision_information_ready is False
    assert report.internal_blockers == ()
    assert "no runtime provider activations are active" in report.external_blockers


def test_all_markets_mechanical_rehearsal_executes_every_classified_class(
    tmp_path: Path,
) -> None:
    report = run_all_markets_paper_rehearsal(
        evaluated_at=AS_OF,
        working_directory=tmp_path / "rehearsal",
    )

    assert report.complete is True
    assert report.fill_count == len(report.expected_asset_classes) == 13
    assert report.filled_asset_classes == report.expected_asset_classes
    assert report.reconciliation_difference < 1e-7
    assert report.ending_cash > 0.0

    retry = run_all_markets_paper_rehearsal(
        evaluated_at=AS_OF,
        working_directory=tmp_path / "rehearsal",
    )
    assert retry.to_dict() == report.to_dict()


def test_complete_external_activation_can_reach_paper_ready(tmp_path: Path) -> None:
    import json
    from datetime import timedelta

    from governance import (
        AssetClassApproval,
        AssetClassApprovalState,
        AssetClassCapabilityProfile,
        CustodySettlementModel,
        TradingSessionModel,
        UNIVERSAL_GOVERNED_ASSET_CLASSES,
    )
    from governance.decision_information_activation import (
        DecisionInformationSourceActivation,
    )
    from governance.provider_activation import ProviderActivation

    manifest = load_data_readiness_manifest(
        "config/all_markets_data_readiness.json"
    )
    information_manifest = load_maximum_decision_information_manifest(
        "config/maximum_decision_information_scope.json"
    )
    provider_store = SQLiteProviderActivationStore(tmp_path / "providers.db")
    information_store = SQLiteDecisionInformationActivationStore(
        tmp_path / "information.db"
    )
    asset_store = SQLiteAssetClassApprovalStore(tmp_path / "assets.db")
    environment: dict[str, str] = {}
    binding_paths: list[Path] = []
    for provider in manifest.providers:
        provider_store.append(
            ProviderActivation(
                identifier=f"activation:{provider.identifier}:test",
                provider_identifier=provider.identifier,
                provider_name=f"Activated {provider.provider_name}",
                enabled=True,
                approved_domains=provider.domains,
                authoritative_domains=provider.authoritative_domains,
                usage_rights_approved=True,
                point_in_time_supported=True,
                historical_coverage_supported=True,
                provenance_complete=True,
                service_level_defined=True,
                storage_and_backup_approved=True,
                derived_analytics_approved=True,
                paper_simulation_approved=True,
                certification_identifier=f"certification:{provider.identifier}",
                approved_by="data-governance-committee",
                rationale="Complete controlled-paper provider activation fixture.",
                approved_at=AS_OF - timedelta(days=2),
                effective_at=AS_OF - timedelta(days=1),
                expires_at=AS_OF + timedelta(days=30),
                source_identifiers=(f"contract:{provider.identifier}",),
            )
        )
        environment.update(
            {
                name: "configured-for-test"
                for name in provider.credential_environment_variables
            }
        )
        dataset_types = {
            DATA_DOMAIN_DATASET_TYPE[domain] for domain in provider.domains
        }
        if provider.identifier == "commercial-global-market-data":
            from data.provider_dataset import ProviderDatasetType

            dataset_types.add(ProviderDatasetType.CANDIDATE_SCREENING)
        binding_path = tmp_path / f"market-{provider.identifier}.json"
        binding_path.write_text(
            json.dumps(
                {
                    "schema_version": "configured-dataset-provider.v1",
                    "provider_identifier": provider.identifier,
                    "source_version": "test.v1",
                    "base_url": "https://provider.example.test/api/",
                    "bindings": [
                        {
                            "dataset_type": item.value,
                            "path": f"v1/{item.value}/{{symbol}}",
                        }
                        for item in sorted(
                            dataset_types, key=lambda value: value.value
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )
        binding_paths.append(binding_path)

    for source in information_manifest.sources:
        information_store.append(
            DecisionInformationSourceActivation(
                identifier=f"activation:{source.identifier}:test",
                source_identifier=source.identifier,
                source_name=f"Activated {source.source_name}",
                enabled=True,
                approved_domains=source.domains,
                authoritative_domains=source.authoritative_domains,
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
                certification_identifier=f"certification:{source.identifier}",
                approved_by="information-governance-committee",
                rationale=(
                    "Complete controlled-paper decision-information fixture."
                ),
                approved_at=AS_OF - timedelta(days=2),
                effective_at=AS_OF - timedelta(days=1),
                expires_at=AS_OF + timedelta(days=30),
                evidence_identifiers=(f"contract:{source.identifier}",),
            )
        )
        environment.update(
            {
                name: "configured-for-test"
                for name in source.credential_environment_variables
            }
        )
        binding_path = tmp_path / f"information-{source.identifier}.json"
        binding_path.write_text(
            json.dumps(
                {
                    "schema_version": "configured-dataset-provider.v1",
                    "provider_identifier": source.identifier,
                    "source_version": "test.v1",
                    "base_url": "https://information.example.test/api/",
                    "bindings": [
                        {
                            "dataset_type": "decision_information",
                            "path": "v1/decision_information/{symbol}",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        binding_paths.append(binding_path)

    structures = {
        "international_equity": (
            "LSE", "GB", "common_stock", "exchange_local",
            "broker_custodied_security",
        ),
        "fixed_income": (
            "TRACE", "US", "bond", "dealer_24_5",
            "central_securities_depository",
        ),
        "commodity": (
            "CME", "US", "future", "exchange_local", "futures_clearing",
        ),
        "fx": (
            "EBS", "GLOBAL", "spot", "continuous_24_5",
            "prime_broker_spot_fx",
        ),
        "crypto": (
            "COINBASE", "GLOBAL", "token", "continuous_24_7",
            "qualified_digital_asset_custody",
        ),
        "real_estate": (
            "NYSE", "US", "common_stock", "exchange_local",
            "broker_custodied_security",
        ),
        "future": (
            "CME", "US", "future", "exchange_local", "futures_clearing",
        ),
        "option": (
            "CBOE", "US", "option", "exchange_local", "options_clearing",
        ),
        "volatility": (
            "CFE", "US", "future", "exchange_local", "futures_clearing",
        ),
        "alternative": (
            "NYSEARCA", "US", "fund", "exchange_local",
            "broker_custodied_security",
        ),
    }
    for asset_class in UNIVERSAL_GOVERNED_ASSET_CLASSES:
        venue, country, instrument_type, session, custody = structures[
            asset_class.value
        ]
        derivative = instrument_type in {"future", "perpetual", "option"}
        profile = AssetClassCapabilityProfile(
            asset_class=asset_class,
            state=AssetClassApprovalState.PAPER_ELIGIBLE,
            approved_venues=(venue,),
            approved_country_codes=(country,),
            base_currency="USD",
            supported_quote_currencies=("USD",),
            trading_session_model=TradingSessionModel(session),
            custody_settlement_model=CustodySettlementModel(custody),
            allowed_instrument_types=(instrument_type,),
            maximum_gross_leverage=1.0,
            identity_model_version="identity.v1",
            valuation_model_version="valuation.v1",
            expected_return_model_version="expected-return.v1",
            liquidity_model_version="liquidity.v1",
            cost_model_version="cost.v1",
            portfolio_risk_model_version="risk.v1",
            execution_model_version="execution.v1",
            thesis_model_version="thesis.v1",
            evaluation_model_version="evaluation.v1",
            contract_model_version="contract.v1" if derivative else None,
            margin_model_version="margin.v1" if derivative else None,
            lifecycle_model_version="lifecycle.v1" if derivative else None,
            roll_model_version=(
                "roll.v1"
                if instrument_type in {"future", "perpetual"}
                else None
            ),
            security_master_certification_identifier="cert:security-master",
            market_data_certification_identifier="cert:market-data",
            analytical_evidence_certification_identifier="cert:evidence",
            execution_certification_identifier="cert:execution",
            custody_settlement_identifier="cert:custody",
            source_identifiers=("source:activation-test",),
            limitations=("paper-only",),
        )
        asset_store.append(
            AssetClassApproval(
                identifier=f"approval:{asset_class.value}:test",
                profile=profile,
                approved_at=AS_OF - timedelta(days=2),
                effective_at=AS_OF - timedelta(days=1),
                expires_at=AS_OF + timedelta(days=30),
                governance_identifier="governance:all-markets-test",
                process_version="process:test",
                code_version="commit:test",
                rationale="Complete all-market paper capability fixture.",
            )
        )

    report = assess_universal_paper_market_readiness(
        manifest=manifest,
        information_manifest=information_manifest,
        evaluated_at=AS_OF,
        environment=environment,
        provider_activation_store=provider_store,
        decision_information_activation_store=information_store,
        asset_class_approval_store=asset_store,
        provider_binding_paths=binding_paths,
        derivative_data_certification=DerivativeDataCertificationReport(
            evaluated_at=AS_OF,
            certified=True,
            contract_count=3,
            margin_count=3,
            volatility_surface_count=1,
            covered_venues=("CME", "ICE", "OCC"),
            blockers=(),
        ),
    )

    assert report.internal_ready is True
    assert report.market_data_ready is True
    assert report.decision_information_ready is True
    assert report.paper_ready is True
    assert report.external_blockers == ()
