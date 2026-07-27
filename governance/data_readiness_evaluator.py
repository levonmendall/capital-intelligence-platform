"""All-markets data readiness evaluation."""
from __future__ import annotations
import os
from typing import Mapping
from governance.data_readiness_models import (
    AllMarketsDataManifest, AllMarketsDataReadinessReport, AllMarketsDataReadinessState,
    DatasetReadinessAssessment, MarketDataReadinessAssessment, MarketDataScopeState,
)
from cio.models import CandidateAssetClass

class AllMarketsDataReadinessEvaluator:
    """Evaluate one complete data manifest against runtime configuration."""

    def evaluate(
        self,
        manifest: AllMarketsDataManifest,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> AllMarketsDataReadinessReport:
        if not isinstance(manifest, AllMarketsDataManifest):
            raise TypeError("manifest must be AllMarketsDataManifest")
        runtime = os.environ if environment is None else environment
        provider_by_id = {
            provider.identifier: provider for provider in manifest.providers
        }
        market_results: list[MarketDataReadinessAssessment] = []
        blockers: list[str] = []
        missing_environment: set[str] = set()

        for market in manifest.markets:
            dataset_results: list[DatasetReadinessAssessment] = []
            for requirement in market.requirements:
                ready_providers: list[str] = []
                requirement_blockers: list[str] = []
                for provider_id in requirement.provider_identifiers:
                    provider = provider_by_id[provider_id]
                    deficiencies = provider.deficiencies(
                        runtime,
                        domain=requirement.domain,
                        paper_use=(
                            market.state is MarketDataScopeState.PAPER_ELIGIBLE
                        ),
                        authoritative_required=(
                            requirement.authoritative_required
                        ),
                    )
                    if not deficiencies:
                        ready_providers.append(provider_id)
                    else:
                        requirement_blockers.append(
                            f"{provider_id}: " + "; ".join(deficiencies)
                        )
                        for variable in provider.credential_environment_variables:
                            if not str(runtime.get(variable, "")).strip():
                                missing_environment.add(variable)
                result = DatasetReadinessAssessment(
                    asset_class=market.asset_class,
                    market_state=market.state,
                    domain=requirement.domain,
                    required_provider_identifiers=(
                        requirement.provider_identifiers
                    ),
                    ready_provider_identifiers=tuple(ready_providers),
                    minimum_ready_providers=(
                        requirement.minimum_ready_providers
                    ),
                    blockers=tuple(requirement_blockers),
                )
                dataset_results.append(result)
                if not result.ready:
                    blockers.append(
                        f"{market.asset_class.value}/{requirement.domain.value}: "
                        f"requires {requirement.minimum_ready_providers} ready "
                        f"provider(s), found {len(ready_providers)}"
                    )
            market_results.append(
                MarketDataReadinessAssessment(
                    asset_class=market.asset_class,
                    state=market.state,
                    rationale=market.rationale,
                    datasets=tuple(dataset_results),
                )
            )

        all_declared = set(item.asset_class for item in manifest.markets) == set(
            CandidateAssetClass
        )
        if manifest.require_complete_candidate_scope and not all_declared:
            blockers.append("complete candidate market scope is not declared")

        non_prohibited = tuple(
            item
            for item in market_results
            if item.state is not MarketDataScopeState.PROHIBITED
        )
        paper = tuple(
            item
            for item in market_results
            if item.state is MarketDataScopeState.PAPER_ELIGIBLE
        )
        decision = tuple(
            item
            for item in market_results
            if item.state is MarketDataScopeState.DECISION_RELEVANT
        )
        evidence = tuple(
            item
            for item in market_results
            if item.state is MarketDataScopeState.EVIDENCE_ONLY
        )
        global_ready = bool(non_prohibited) and all(
            item.ready for item in non_prohibited
        )
        paper_ready = bool(paper) and all(item.ready for item in paper)
        decision_ready = not decision or all(item.ready for item in decision)
        evidence_ready = not evidence or all(item.ready for item in evidence)

        if global_ready and all_declared:
            state = AllMarketsDataReadinessState.READY
        elif any(item.ready for item in non_prohibited):
            state = AllMarketsDataReadinessState.PARTIAL
        else:
            state = AllMarketsDataReadinessState.BLOCKED

        return AllMarketsDataReadinessReport(
            manifest_identifier=manifest.identifier,
            schema_version=manifest.schema_version,
            reporting_currency=manifest.reporting_currency,
            state=state,
            all_candidate_markets_declared=all_declared,
            global_test_data_ready=global_ready and all_declared,
            paper_eligible_data_ready=paper_ready,
            decision_relevant_data_ready=decision_ready,
            evidence_only_data_ready=evidence_ready,
            missing_environment_variables=tuple(sorted(missing_environment)),
            markets=tuple(market_results),
            blockers=tuple(blockers),
        )


