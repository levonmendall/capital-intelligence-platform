from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio.models import CandidateAssetClass
from governance.instrument_paper_eligibility import (
    InstrumentPaperEligibilityAuthority,
    InstrumentPaperEligibilityState,
    SQLiteInstrumentPaperEligibilityStore,
)
from operations.instrument_eligibility_factory import (
    AutomaticInstrumentEligibilityFactory,
    EligibilityCertificationPolicy,
)
from operations.universal_capability_graph import (
    AssetFamily,
    InstrumentCapabilityEvidence,
    evaluate_capabilities,
    family_for_instrument,
    investability_coverage,
    required_capabilities,
)
from operations.universal_paper_contract import (
    NormalizedInvestmentView,
    PaperOrderIntent,
    translate_paper_intent,
)


NOW = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)


def _evidence(
    *,
    asset_class: CandidateAssetClass = CandidateAssetClass.US_EQUITY,
    instrument_type: str = "stock",
    missing: frozenset[str] = frozenset(),
    provider_authority: bool = False,
    average_daily_dollar_volume: float = 50_000_000.0,
) -> InstrumentCapabilityEvidence:
    family = family_for_instrument(asset_class, instrument_type)
    capabilities = (
        frozenset() if family is None else required_capabilities(family)
    ) - missing
    return InstrumentCapabilityEvidence(
        instrument_identifier="instrument:test:abc",
        symbol="ABC",
        asset_class=asset_class,
        venue="XNAS",
        country_code="US",
        instrument_type=instrument_type,
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=4),
        capabilities=capabilities,
        proof_identifiers={name: f"proof:{name}:1" for name in capabilities},
        source_identifiers=("qualified-evidence:generation-1",),
        average_daily_dollar_volume=average_daily_dollar_volume,
        minimum_average_daily_dollar_volume=1_000_000.0,
        leverage_multiplier=1.0,
        maximum_gross_leverage=1.0,
        provider_authority=provider_authority,
    )


def _policy() -> EligibilityCertificationPolicy:
    return EligibilityCertificationPolicy(
        asset_class_approval_identifier="approval:us-equity-paper:v1",
        governance_identifier="governance:cio-paper:v1",
        process_version="universal-capability-factory.v1",
        code_version="test-sha",
        maximum_position_weight=0.20,
        maximum_participation_rate=0.01,
        certification_lifetime=timedelta(hours=2),
    )


def test_exact_instrument_type_resolves_lifecycle_family() -> None:
    assert (
        family_for_instrument(CandidateAssetClass.COMMODITY, "etf")
        is AssetFamily.FUND
    )
    assert (
        family_for_instrument(CandidateAssetClass.COMMODITY, "future")
        is AssetFamily.FUTURE
    )
    assert (
        family_for_instrument(CandidateAssetClass.VOLATILITY, "option")
        is AssetFamily.OPTION
    )


def test_provider_visibility_cannot_become_authority() -> None:
    with pytest.raises(ValueError, match="providers cannot grant"):
        _evidence(provider_authority=True)


def test_missing_family_lifecycle_proof_fails_closed() -> None:
    evidence = _evidence(missing=frozenset({"corporate_actions"}))
    evaluation = evaluate_capabilities(evidence, evaluated_at=NOW + timedelta(minutes=1))
    assert evaluation.discovered is True
    assert evaluation.analytically_supported is True
    assert evaluation.lifecycle_valid is False
    assert evaluation.paper_executable is False
    assert evaluation.certifiable is False
    assert "missing_capability:corporate_actions" in evaluation.blockers


def test_complete_graph_certifies_through_existing_append_only_authority(tmp_path) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    factory = AutomaticInstrumentEligibilityFactory(store)
    transition = factory.reconcile(
        _evidence(), policy=_policy(), evaluated_at=NOW + timedelta(minutes=1)
    )
    assert transition.action == "certified"
    assert transition.cio_authority is False
    assert transition.real_money_authorized is False
    assert store.verify_integrity() is True

    instrument = SimpleNamespace(
        instrument_id="instrument:test:abc",
        symbol="ABC",
        asset_class=CandidateAssetClass.US_EQUITY,
        venue="XNAS",
        country_code="US",
        instrument_type="stock",
        average_daily_dollar_volume=50_000_000.0,
        leverage_multiplier=1.0,
    )
    assessment = InstrumentPaperEligibilityAuthority(store).assess(
        instrument, evaluated_at=NOW + timedelta(minutes=2)
    )
    assert assessment.paper_allocatable is True
    certification = store.active(
        "instrument:test:abc", evaluated_at=NOW + timedelta(minutes=2)
    )
    assert certification is not None
    assert any(
        item.startswith("capability-graph:universal-capability-graph.v1")
        for item in certification.source_identifiers
    )


def test_degraded_graph_automatically_suspends_existing_certification(tmp_path) -> None:
    store = SQLiteInstrumentPaperEligibilityStore(tmp_path / "eligibility.db")
    factory = AutomaticInstrumentEligibilityFactory(store)
    factory.reconcile(
        _evidence(), policy=_policy(), evaluated_at=NOW + timedelta(minutes=1)
    )
    transition = factory.reconcile(
        _evidence(missing=frozenset({"reconciliation"})),
        policy=_policy(),
        evaluated_at=NOW + timedelta(minutes=2),
    )
    assert transition.action == "suspended"
    assert "missing_capability:reconciliation" in transition.blockers
    assert (
        store.active("instrument:test:abc", evaluated_at=NOW + timedelta(minutes=3))
        is None
    )
    history = store.certifications("instrument:test:abc")
    assert [item.state for item in history] == [
        InstrumentPaperEligibilityState.CERTIFIED,
        InstrumentPaperEligibilityState.SUSPENDED,
    ]
    assert store.verify_integrity() is True


def test_liquidity_degradation_blocks_automatic_certification() -> None:
    evaluation = evaluate_capabilities(
        _evidence(average_daily_dollar_volume=100_000.0),
        evaluated_at=NOW + timedelta(minutes=1),
    )
    assert evaluation.certifiable is False
    assert "liquidity_below_certified_floor" in evaluation.blockers


def test_universal_order_contract_uses_family_adapter_and_stays_paper_only() -> None:
    evidence = _evidence(
        asset_class=CandidateAssetClass.OPTION,
        instrument_type="option",
    )
    evaluation = evaluate_capabilities(evidence, evaluated_at=NOW + timedelta(minutes=1))
    instruction = translate_paper_intent(
        PaperOrderIntent(
            instrument_identifier=evidence.instrument_identifier,
            target_notional=3_500.0,
            side="buy",
        ),
        NormalizedInvestmentView(
            instrument_identifier=evidence.instrument_identifier,
            asset_family=AssetFamily.OPTION,
            reference_price=2.50,
            contract_multiplier=100.0,
        ),
        evaluation,
    )
    assert instruction.signed_quantity == 14.0
    assert instruction.quantity_kind == "contracts"
    assert instruction.execution_mode == "paper"
    assert instruction.real_money_authorized is False


def test_global_investability_coverage_separates_certification_from_cio_eligibility() -> None:
    evaluation = evaluate_capabilities(
        _evidence(), evaluated_at=NOW + timedelta(minutes=1)
    )
    coverage = investability_coverage(
        (evaluation,),
        paper_certified_identifiers=(evaluation.instrument_identifier,),
        cio_eligible_identifiers=(),
    )
    assert coverage["discovered"] == 1
    assert coverage["paper_executable"] == 1
    assert coverage["paper_certified"] == 1
    assert coverage["cio_eligible"] == 0
    assert coverage["provider_authority"] is False
    assert coverage["real_money_authorized"] is False


def test_cio_eligibility_cannot_exceed_paper_certification() -> None:
    evaluation = evaluate_capabilities(
        _evidence(), evaluated_at=NOW + timedelta(minutes=1)
    )
    with pytest.raises(ValueError, match="must be paper-certified"):
        investability_coverage(
            (evaluation,),
            paper_certified_identifiers=(),
            cio_eligible_identifiers=(evaluation.instrument_identifier,),
        )
