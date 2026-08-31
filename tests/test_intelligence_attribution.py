from datetime import datetime, timezone

from evaluation.committee_cio_trace import CommitteeCIOInformationTrace
from evaluation.intelligence_attribution import build_cycle_intelligence_attribution


_AS_OF = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
_REQUIRED_ROLES = (
    "macro_economic",
    "market",
    "cross_asset_forecast",
    "fundamental_valuation",
    "portfolio_risk",
    "evidence_governance",
)


def _trace(
    *,
    candidate_identifier="candidate:BTC",
    evidence=(),
    specialist_origins=(),
    include_all_specialists=True,
    cio_action="hold",
):
    specialists = []
    roles = _REQUIRED_ROLES if include_all_specialists else ("market",)
    for role in roles:
        origins = specialist_origins if role == "market" else ()
        specialists.append(
            {
                "role": role,
                "evidence_origin_identifiers": list(origins),
            }
        )
    return CommitteeCIOInformationTrace(
        payload={
            "decision_identifier": f"decision:{candidate_identifier}",
            "candidate_identifier": candidate_identifier,
            "as_of": _AS_OF.isoformat(),
            "source": {"candidate_evidence_identifiers": list(evidence)},
            "specialists": specialists,
            "cio_decision": {"action": cio_action},
        }
    )


def _by_capability(attribution, capability):
    return next(
        item for item in attribution.capabilities if item.capability == capability
    )


def test_observed_evidence_is_attributed_to_specialist_and_cio():
    evidence_id = "predictive-market-intelligence:model-ensemble:evidence-42"
    attribution = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:1",
        as_of=_AS_OF,
        traces=(
            _trace(
                evidence=(evidence_id,),
                specialist_origins=(evidence_id,),
            ),
        ),
    )

    item = _by_capability(attribution, "predictive_market_intelligence")
    assert item.invocation_state == "observed"
    assert item.evidence_produced is True
    assert item.evidence_identifiers == (evidence_id,)
    assert item.candidate_identifiers == ("candidate:BTC",)
    assert item.specialist_roles_consuming == ("market",)
    assert item.reached_cio is True
    assert item.material_decision_influence == "not_counterfactually_observable"
    assert item.role == "advisory"


def test_presence_without_specialist_consumption_does_not_claim_cio_reach():
    evidence_id = "global-opportunity-radar:evidence-7"
    attribution = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:2",
        as_of=_AS_OF,
        traces=(_trace(evidence=(evidence_id,)),),
    )

    item = _by_capability(attribution, "global_opportunity_radar")
    assert item.invocation_state == "observed"
    assert item.evidence_produced is True
    assert item.specialist_roles_consuming == ()
    assert item.reached_cio is False


def test_optional_capabilities_distinguish_unobserved_from_unobservable():
    attribution = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:3",
        as_of=_AS_OF,
        traces=(_trace(),),
    )

    assert (
        _by_capability(attribution, "canonical_exposure_graph").invocation_state
        == "not_observed"
    )
    assert (
        _by_capability(attribution, "mispriced_change").invocation_state
        == "invocation_not_observable"
    )
    assert (
        _by_capability(attribution, "global_compound_optimizer").invocation_state
        == "invocation_not_observable"
    )


def test_six_specialist_committee_requires_all_governed_roles():
    complete = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:4",
        as_of=_AS_OF,
        traces=(_trace(),),
    )
    incomplete = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:5",
        as_of=_AS_OF,
        traces=(_trace(include_all_specialists=False),),
    )

    complete_item = _by_capability(complete, "six_specialist_committee")
    incomplete_item = _by_capability(incomplete, "six_specialist_committee")
    assert complete_item.invocation_state == "observed"
    assert complete_item.reached_cio is True
    assert set(complete_item.specialist_roles_consuming) == set(_REQUIRED_ROLES)
    assert incomplete_item.invocation_state == "not_observed"
    assert incomplete_item.reached_cio is False


def test_secret_looking_evidence_is_not_emitted_in_safe_samples():
    attribution = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:6",
        as_of=_AS_OF,
        traces=(
            _trace(
                evidence=(
                    "predictive-market-intelligence:token=do-not-emit",
                    "predictive-market-intelligence:safe-evidence",
                ),
            ),
        ),
    )

    item = _by_capability(attribution, "predictive_market_intelligence")
    assert item.invocation_state == "observed"
    assert item.evidence_identifiers == (
        "predictive-market-intelligence:safe-evidence",
    )


def test_aggregate_and_authority_are_explicitly_non_authoritative():
    evidence_id = "derived-capital-flow:BTC"
    attribution = build_cycle_intelligence_attribution(
        cycle_identifier="cycle:7",
        as_of=_AS_OF,
        traces=(
            _trace(
                evidence=(evidence_id,),
                specialist_origins=(evidence_id,),
            ),
        ),
    )
    payload = attribution.to_dict()

    assert payload["record_kind"] == "cycle_intelligence_attribution"
    assert payload["aggregate"]["declared_capability_count"] == 15
    assert payload["aggregate"]["observed_invocation_count"] == 2
    assert payload["aggregate"]["evidence_producing_count"] == 1
    assert payload["aggregate"]["specialist_consumed_count"] == 2
    assert payload["aggregate"]["reached_cio_count"] == 2
    assert payload["authority"] == {
        "decision_authority": False,
        "construction_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "allocation_authority": False,
        "paper_only": True,
    }
    assert all(
        item["material_decision_influence"]
        == "not_counterfactually_observable"
        for item in payload["capabilities"]
    )
