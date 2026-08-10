"""Portfolio-value-ranked decision-information depth program.

Rank missing decision information by its potential contribution to sustainable
long-term compounded portfolio dollar value. The program combines the existing
candidate decision-readiness policy, Value of Information, and canonical information
capability audit. It is diagnostic only: provider presence is never treated as
certification, and this module cannot create a candidate, lower a hurdle, authorize
capital, size a position, or execute.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

from governance.decision_readiness import CandidateDecisionReadinessPolicy
from intelligence.asset_underwriting import UnderwritingDimension
from intelligence.value_of_information import MissingInformationInput, ValueOfInformationEngine
from operations.information_gap_audit import build_information_gap_audit


# Research/data domains come only from maximum_decision_information_scope.json.
# Vehicle mechanics remain in the separate security-master/market/execution stack.
_DIMENSION_DOMAINS: dict[UnderwritingDimension, tuple[str, ...]] = {
    UnderwritingDimension.IDENTITY: (),
    UnderwritingDimension.MARKET_DATA: (),
    UnderwritingDimension.LIQUIDITY: (),
    UnderwritingDimension.MACRO: (
        "central_bank_communications",
        "government_policy_regulation",
        "labor_web_activity",
    ),
    UnderwritingDimension.FUNDAMENTALS: (
        "filings_corporate_disclosures",
        "management_guidance",
        "analyst_estimates_revisions",
    ),
    UnderwritingDimension.VALUATION: ("analyst_estimates_revisions",),
    UnderwritingDimension.CARRY: (),
    UnderwritingDimension.CURVE: (),
    UnderwritingDimension.CREDIT: ("credit_ratings_defaults",),
    UnderwritingDimension.CURRENCY: (
        "central_bank_communications",
        "fund_flows_positioning",
    ),
    UnderwritingDimension.PHYSICAL_BALANCE: (
        "commodity_physical_balances",
        "supply_chain_shipping_inventories",
        "weather_climate_disasters",
        "energy_grid_power",
    ),
    UnderwritingDimension.POSITIONING: (
        "futures_positioning",
        "fund_flows_positioning",
        "short_interest_securities_lending",
        "insider_institutional_ownership",
    ),
    UnderwritingDimension.ONCHAIN: ("onchain_crypto_network",),
    UnderwritingDimension.DERIVATIVES: (
        "options_implied_expectations",
        "futures_positioning",
    ),
    UnderwritingDimension.CASH_FLOW: (
        "filings_corporate_disclosures",
        "management_guidance",
    ),
    UnderwritingDimension.CORPORATE_ACTIONS: (
        "filings_corporate_disclosures",
        "management_guidance",
        "insider_institutional_ownership",
    ),
    UnderwritingDimension.HISTORY: (),
    UnderwritingDimension.EXECUTION: (),
}


class InformationDepthResolutionState(str, Enum):
    EXISTING_DECISION_CERTIFIED = "existing_decision_certified"
    EXISTING_MONITORED_NEEDS_CERTIFICATION = "existing_monitored_needs_certification"
    EXISTING_NEEDS_POINT_IN_TIME_HISTORY = "existing_needs_point_in_time_history"
    PARTIAL_EXISTING_COVERAGE_NEW_SOURCE_REQUIRED = (
        "partial_existing_coverage_new_source_required"
    )
    NEW_OR_PREMIUM_SOURCE_REQUIRED = "new_or_premium_source_required"
    CORE_CAPABILITY_STACK_REQUIRED = "core_capability_stack_required"


@dataclass(frozen=True, slots=True)
class CandidateInformationDepthDemand:
    candidate_identifier: str
    dimension: UnderwritingDimension
    economic_exposure_class: str
    capital_blocking: bool
    deep_economic_gap: bool
    value_of_information_score: float
    expected_dollar_opportunity_at_stake: float
    portfolio_value: float
    compounding_value_score: float
    mapped_domains: tuple[str, ...]
    existing_capability_identifiers: tuple[str, ...]
    resolution_state: InformationDepthResolutionState
    rationale: tuple[str, ...]
    investment_authority: bool = False
    schema_version: str = "candidate-information-depth-demand.v2"

    def __post_init__(self) -> None:
        if not self.candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not isinstance(self.dimension, UnderwritingDimension):
            raise TypeError("dimension must be UnderwritingDimension")
        for name in (
            "value_of_information_score",
            "expected_dollar_opportunity_at_stake",
            "portfolio_value",
            "compounding_value_score",
        ):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.portfolio_value <= 0.0:
            raise ValueError("portfolio_value must be positive")
        if not 0.0 <= self.value_of_information_score <= 1.0:
            raise ValueError("value_of_information_score must be between zero and one")
        if not 0.0 <= self.compounding_value_score <= 1.0:
            raise ValueError("compounding_value_score must be between zero and one")
        if self.investment_authority:
            raise ValueError("information-depth demand cannot authorize capital")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "dimension": self.dimension.value,
            "economic_exposure_class": self.economic_exposure_class,
            "capital_blocking": self.capital_blocking,
            "deep_economic_gap": self.deep_economic_gap,
            "value_of_information_score": round(self.value_of_information_score, 8),
            "expected_dollar_opportunity_at_stake": round(
                self.expected_dollar_opportunity_at_stake, 2
            ),
            "portfolio_value": round(self.portfolio_value, 2),
            "compounding_value_score": round(self.compounding_value_score, 8),
            "mapped_domains": list(self.mapped_domains),
            "existing_capability_identifiers": list(
                self.existing_capability_identifiers
            ),
            "resolution_state": self.resolution_state.value,
            "rationale": list(self.rationale),
            "investment_authority": False,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class DecisionInformationDepthProgram:
    portfolio_value: float
    candidate_count: int
    demand_count: int
    total_expected_dollar_opportunity_at_stake: float
    demands: tuple[CandidateInformationDepthDemand, ...]
    domain_rollup: tuple[dict[str, Any], ...]
    investment_authority: bool = False
    execution_authority: bool = False
    schema_version: str = "decision-information-depth-program.v2"

    def __post_init__(self) -> None:
        if self.portfolio_value <= 0.0:
            raise ValueError("portfolio_value must be positive")
        if self.investment_authority or self.execution_authority:
            raise ValueError("information-depth program is diagnostic only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_value": round(self.portfolio_value, 2),
            "candidate_count": self.candidate_count,
            "demand_count": self.demand_count,
            "total_expected_dollar_opportunity_at_stake": round(
                self.total_expected_dollar_opportunity_at_stake, 2
            ),
            "demands": [item.to_dict() for item in self.demands],
            "domain_rollup": list(self.domain_rollup),
            "investment_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _domain_rows(audit: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["domain"]): row
        for row in audit.get("domain_status", ())
        if isinstance(row, Mapping) and str(row.get("domain", "")).strip()
    }


def _resolution_state(
    domains: tuple[str, ...],
    rows: Mapping[str, Mapping[str, Any]],
) -> tuple[InformationDepthResolutionState, tuple[str, ...]]:
    """Resolve the *complete* mapped dimension, never just one favorable subdomain."""

    if not domains:
        return InformationDepthResolutionState.CORE_CAPABILITY_STACK_REQUIRED, ()

    relevant = {domain: rows.get(domain) for domain in domains}
    capabilities = tuple(
        dict.fromkeys(
            str(identifier)
            for row in relevant.values()
            if isinstance(row, Mapping)
            for identifier in row.get("capability_identifiers", ())
            if str(identifier).strip()
        )
    )
    present_rows = tuple(row for row in relevant.values() if isinstance(row, Mapping))
    certified_domains = {
        domain
        for domain, row in relevant.items()
        if isinstance(row, Mapping)
        and bool(row.get("decision_certified_and_healthy", False))
    }
    monitored_domains = {
        domain
        for domain, row in relevant.items()
        if isinstance(row, Mapping) and bool(row.get("monitored", False))
    }
    historical_domains = {
        domain
        for domain, row in relevant.items()
        if isinstance(row, Mapping)
        and bool(row.get("historical_capability_present", False))
    }
    required = set(domains)

    if certified_domains == required:
        return InformationDepthResolutionState.EXISTING_DECISION_CERTIFIED, capabilities

    covered = certified_domains | monitored_domains
    if covered == required:
        # Every required subdomain exists. Distinguish a certification problem from
        # a missing PIT-history problem; neither is described as fully certified.
        if historical_domains == required:
            return (
                InformationDepthResolutionState.EXISTING_MONITORED_NEEDS_CERTIFICATION,
                capabilities,
            )
        return (
            InformationDepthResolutionState.EXISTING_NEEDS_POINT_IN_TIME_HISTORY,
            capabilities,
        )

    if covered:
        return (
            InformationDepthResolutionState.PARTIAL_EXISTING_COVERAGE_NEW_SOURCE_REQUIRED,
            capabilities,
        )
    return InformationDepthResolutionState.NEW_OR_PREMIUM_SOURCE_REQUIRED, capabilities


def _compounding_value_score(
    *,
    voi_score: float,
    expected_dollar_opportunity_at_stake: float,
    portfolio_value: float,
    blocking: bool,
    deep_gap: bool,
) -> float:
    # A 2% portfolio-value opportunity saturates the wealth-importance term. This
    # prevents a large speculative idea from swamping a genuinely blocking evidence
    # gap while still making research priority sensitive to terminal-dollar impact.
    dollar_importance = min(
        1.0,
        abs(float(expected_dollar_opportunity_at_stake))
        / max(1.0, float(portfolio_value) * 0.02),
    )
    governance_multiplier = 1.0 if blocking else (0.92 if deep_gap else 0.82)
    return round(
        max(
            0.0,
            min(
                1.0,
                governance_multiplier
                * (0.62 * float(voi_score) + 0.38 * dollar_importance),
            ),
        ),
        8,
    )


def build_decision_information_depth_program(
    *,
    candidate_evidence_pairs: Iterable[tuple[object, object]],
    portfolio_value: float,
    expected_dollar_opportunity_by_candidate: Mapping[str, float] | None = None,
    missing_information_inputs: Mapping[
        str, tuple[MissingInformationInput, ...]
    ] | None = None,
    information_gap_audit: Mapping[str, Any] | None = None,
    runtime_report_path: str | Path | None = None,
) -> DecisionInformationDepthProgram:
    """Rank candidate information gaps by potential compounding-dollar impact."""

    if not isfinite(float(portfolio_value)) or float(portfolio_value) <= 0.0:
        raise ValueError("portfolio_value must be positive and finite")
    pairs = tuple(candidate_evidence_pairs)
    expected = {
        str(key): float(value)
        for key, value in dict(
            expected_dollar_opportunity_by_candidate or {}
        ).items()
    }
    supplied_inputs = dict(missing_information_inputs or {})
    audit = dict(
        information_gap_audit
        or build_information_gap_audit(runtime_report_path=runtime_report_path)
    )
    rows = _domain_rows(audit)
    readiness_policy = CandidateDecisionReadinessPolicy()
    voi_engine = ValueOfInformationEngine()
    demands: list[CandidateInformationDepthDemand] = []
    candidate_ids: set[str] = set()

    for candidate, evidence in pairs:
        readiness = readiness_policy.assess(candidate, evidence)
        candidate_ids.add(readiness.candidate_identifier)
        priorities = voi_engine.prioritize(
            readiness=readiness,
            inputs=tuple(
                supplied_inputs.get(readiness.candidate_identifier, ())
            ),
        )
        deep_missing = set(readiness.deep_missing)
        for priority in priorities:
            domains = _DIMENSION_DOMAINS.get(priority.dimension, ())
            state, capability_ids = _resolution_state(domains, rows)
            dollar_at_stake = expected.get(readiness.candidate_identifier, 0.0)
            deep_gap = priority.dimension in deep_missing
            demands.append(
                CandidateInformationDepthDemand(
                    candidate_identifier=readiness.candidate_identifier,
                    dimension=priority.dimension,
                    economic_exposure_class=(
                        readiness.economic_exposure_class
                        or readiness.asset_class
                    ).value,
                    capital_blocking=priority.blocking,
                    deep_economic_gap=deep_gap,
                    value_of_information_score=priority.priority_score,
                    expected_dollar_opportunity_at_stake=dollar_at_stake,
                    portfolio_value=float(portfolio_value),
                    compounding_value_score=_compounding_value_score(
                        voi_score=priority.priority_score,
                        expected_dollar_opportunity_at_stake=dollar_at_stake,
                        portfolio_value=float(portfolio_value),
                        blocking=priority.blocking,
                        deep_gap=deep_gap,
                    ),
                    mapped_domains=domains,
                    existing_capability_identifiers=capability_ids,
                    resolution_state=state,
                    rationale=tuple(
                        dict.fromkeys(
                            (
                                *priority.rationale,
                                f"expected dollar opportunity at stake=${dollar_at_stake:,.2f}",
                                f"resolution state={state.value}",
                            )
                        )
                    ),
                )
            )

    ordered = tuple(
        sorted(
            demands,
            key=lambda item: (
                item.capital_blocking,
                item.compounding_value_score,
                abs(item.expected_dollar_opportunity_at_stake),
                item.value_of_information_score,
                item.candidate_identifier,
                item.dimension.value,
            ),
            reverse=True,
        )
    )
    rollup_map: dict[str, dict[str, Any]] = {}
    for item in ordered:
        for domain in item.mapped_domains or ("core_capability_stack",):
            row = rollup_map.setdefault(
                domain,
                {
                    "domain": domain,
                    "demand_count": 0,
                    "capital_blocking_demand_count": 0,
                    "expected_dollar_opportunity_at_stake": 0.0,
                    "highest_compounding_value_score": 0.0,
                    "resolution_states": set(),
                    "candidate_identifiers": set(),
                },
            )
            row["demand_count"] += 1
            row["capital_blocking_demand_count"] += int(item.capital_blocking)
            row["expected_dollar_opportunity_at_stake"] += abs(
                item.expected_dollar_opportunity_at_stake
            )
            row["highest_compounding_value_score"] = max(
                row["highest_compounding_value_score"],
                item.compounding_value_score,
            )
            row["resolution_states"].add(item.resolution_state.value)
            row["candidate_identifiers"].add(item.candidate_identifier)

    rollup: list[dict[str, Any]] = []
    for row in rollup_map.values():
        row["candidate_count"] = len(row["candidate_identifiers"])
        row["candidate_identifiers"] = sorted(row["candidate_identifiers"])
        row["resolution_states"] = sorted(row["resolution_states"])
        row["expected_dollar_opportunity_at_stake"] = round(
            row["expected_dollar_opportunity_at_stake"], 2
        )
        row["highest_compounding_value_score"] = round(
            row["highest_compounding_value_score"], 8
        )
        rollup.append(row)
    rollup.sort(
        key=lambda row: (
            row["capital_blocking_demand_count"],
            row["highest_compounding_value_score"],
            row["expected_dollar_opportunity_at_stake"],
            row["domain"],
        ),
        reverse=True,
    )

    return DecisionInformationDepthProgram(
        portfolio_value=float(portfolio_value),
        candidate_count=len(candidate_ids),
        demand_count=len(ordered),
        total_expected_dollar_opportunity_at_stake=round(
            sum(abs(value) for value in expected.values()), 2
        ),
        demands=ordered,
        domain_rollup=tuple(rollup),
    )


__all__ = [
    "CandidateInformationDepthDemand",
    "DecisionInformationDepthProgram",
    "InformationDepthResolutionState",
    "build_decision_information_depth_program",
]
