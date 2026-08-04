from datetime import UTC, datetime

import pytest

from governance.institutional_data_activation import (
    DatasetActivationState,
    InstitutionalDataset,
    InstitutionalDatasetActivation,
    ProviderOnboardingGates,
    disabled_activation_inventory,
    recommended_activation_order,
)


AS_OF = datetime(2026, 8, 3, tzinfo=UTC)


def test_default_inventory_truthfully_disables_all_unlicensed_datasets():
    inventory = disabled_activation_inventory(assessed_at=AS_OF)
    assert len(inventory) == 18
    assert tuple(item.dataset for item in inventory) == recommended_activation_order()
    assert all(
        item.effective_state is DatasetActivationState.DISABLED
        for item in inventory
    )
    assert all(not item.production_decision_authorized for item in inventory)


def test_api_response_is_not_enough_to_activate_provider():
    incomplete = ProviderOnboardingGates(
        licensing_review=True,
        allowed_use_and_retention_review=False,
        historical_point_in_time_coverage=False,
        provenance_complete=True,
        symbol_identity_reconciliation=True,
        freshness_and_sla_policy=True,
        outage_behavior=True,
        deterministic_fixtures=True,
        certification_scenarios=False,
        data_readiness_activation=False,
        fail_closed_production_binding=False,
    )
    with pytest.raises(ValueError, match="all onboarding gates"):
        InstitutionalDatasetActivation(
            identifier="activation:fund-flows",
            dataset=InstitutionalDataset.FUND_FLOWS,
            provider_identifier="provider:responding-api",
            assessed_at=AS_OF,
            gates=incomplete,
            requested_state=DatasetActivationState.ACTIVE_ADVISORY,
            certification_identifier="cert:incomplete",
        )
