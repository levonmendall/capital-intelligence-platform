"""Concrete production adapter for the scheduled canonical CIO cycle."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from application.eligible_universe import (
    EligibleUniverseError,
    SQLiteCertifiedEligibleUniverseStore,
)
from application.multi_asset_evidence import (
    MultiAssetEvidenceError,
    SQLiteAssetSpecificEvidenceStore,
)
from application.production_context import (
    ProductionContextError,
    SQLiteProductionContextStore,
    _aware,
    _text,
)
from application.production_context_contract import (
    ProductionCanonicalCIOContext,
)
from application.production_context_runtime import (
    RepositoryProductionCanonicalCIOContextProvider as _StoredContextProvider,
)
from committee.specialists import AssetValuationSpecialistContext
from governance import EXPANSION_ASSET_CLASSES
from portfolio.state import SQLiteCanonicalPortfolioStore
from screening import (
    ScreeningEventType,
    SQLiteFullUniverseScreeningStore,
    candidate_from_payload,
)


def _merge_versions(
    *groups: tuple[tuple[str, str], ...],
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    merged: dict[str, str] = {}
    for group in groups:
        for name, version in group:
            existing = merged.get(name)
            if existing is not None and existing != version:
                raise ProductionContextError(
                    f"{field_name} contains conflicting versions for {name}"
                )
            merged[name] = version
    return tuple(sorted(merged.items()))


def _asset_valuation_context(packet) -> AssetValuationSpecialistContext:
    metrics = dict(packet.metrics)
    raw_impact = float(metrics.get("expected_return_impact", 0.0))
    impact = max(-1.0, min(1.0, raw_impact))
    confidence = min(
        0.95,
        max(0.50, 0.40 + 0.10 * packet.independent_origin_count),
    )
    return AssetValuationSpecialistContext(
        as_of=packet.as_of,
        asset_class=packet.asset_class,
        expected_return_impact=impact,
        confidence=confidence,
        valuation_evidence=tuple(
            dict.fromkeys(packet.valuation_basis + packet.return_drivers)
        ),
        contradictory_evidence=packet.risks,
        critical_assumptions=packet.valuation_basis,
        risks=packet.risks,
        limitations=packet.limitations,
        change_conditions=packet.invalidation_conditions,
        evidence_identifiers=tuple(
            dict.fromkeys(
                (packet.identifier, *packet.evidence_identifiers, *packet.originating_fact_identifiers)
            )
        ),
    )


class RepositoryProductionCanonicalCIOContextProvider:
    """Assemble the official CIO briefing package from canonical authorities."""

    name = "CANONICAL_PRODUCTION_CONTEXT_ADAPTER"

    def __init__(
        self,
        *,
        universe_store: SQLiteCertifiedEligibleUniverseStore,
        screening_store: SQLiteFullUniverseScreeningStore,
        portfolio_store: SQLiteCanonicalPortfolioStore,
        context_store: SQLiteProductionContextStore,
        asset_evidence_store: SQLiteAssetSpecificEvidenceStore | None = None,
        portfolio_code: str = "COMPOUNDING",
        process_version: str = "capital-intelligence-investment-process.v1",
        code_version: str | None = None,
    ) -> None:
        if not isinstance(
            universe_store,
            SQLiteCertifiedEligibleUniverseStore,
        ):
            raise TypeError(
                "universe_store must be SQLiteCertifiedEligibleUniverseStore"
            )
        if not isinstance(
            screening_store,
            SQLiteFullUniverseScreeningStore,
        ):
            raise TypeError(
                "screening_store must be SQLiteFullUniverseScreeningStore"
            )
        if not isinstance(portfolio_store, SQLiteCanonicalPortfolioStore):
            raise TypeError(
                "portfolio_store must be SQLiteCanonicalPortfolioStore"
            )
        if not isinstance(context_store, SQLiteProductionContextStore):
            raise TypeError(
                "context_store must be SQLiteProductionContextStore"
            )
        if asset_evidence_store is not None and not isinstance(
            asset_evidence_store,
            SQLiteAssetSpecificEvidenceStore,
        ):
            raise TypeError(
                "asset_evidence_store must be SQLiteAssetSpecificEvidenceStore"
            )
        self.universe_store = universe_store
        self.screening_store = screening_store
        self.portfolio_store = portfolio_store
        self.context_store = context_store
        self.asset_evidence_store = (
            asset_evidence_store
            if asset_evidence_store is not None
            else SQLiteAssetSpecificEvidenceStore(context_store.path)
        )
        self.portfolio_code = _text(
            portfolio_code,
            field_name="portfolio_code",
        ).upper()
        self.process_version = _text(
            process_version,
            field_name="process_version",
        )
        self._stored_provider = _StoredContextProvider(
            screening_store=screening_store,
            portfolio_store=portfolio_store,
            context_store=context_store,
            portfolio_code=self.portfolio_code,
            code_version=code_version,
        )

    @property
    def code_version(self) -> str:
        return self._stored_provider.code_version

    def load_context(
        self,
        *,
        as_of: datetime,
    ) -> ProductionCanonicalCIOContext:
        decision_time = _aware(as_of, field_name="as_of")
        self.universe_store.verify_integrity()
        self.asset_evidence_store.verify_integrity()
        base_context = self._stored_provider.load_context(as_of=decision_time)
        if base_context.manifest is None:
            raise ProductionContextError(
                "repository production context requires an immutable manifest"
            )
        cutoff = base_context.manifest.knowledge_cutoff
        if cutoff > decision_time:
            raise ProductionContextError(
                "production data cutoff follows the decision timestamp; "
                "no canonical CIO cycle authorized"
            )

        publication = self.screening_store.publication(
            base_context.screening_cycle_identifier
        )
        if publication is None:
            raise ProductionContextError(
                "completed full-universe screening publication is unavailable"
            )
        if publication.cycle_identifier != base_context.screening_cycle_identifier:
            raise ProductionContextError(
                "screening publication belongs to another cycle"
            )
        if publication.published_at > decision_time:
            raise ProductionContextError(
                "screening publication was unavailable at the decision timestamp"
            )

        cycle_events = self.screening_store.events(
            base_context.screening_cycle_identifier,
            event_type=ScreeningEventType.CYCLE_STARTED,
        )
        if len(cycle_events) != 1:
            raise ProductionContextError(
                "screening cycle must contain exactly one start boundary"
            )
        boundary = cycle_events[0].payload
        boundary_cycle = _text(
            boundary.get("cycle_identifier"),
            field_name="screening boundary cycle identifier",
        )
        if boundary_cycle != publication.cycle_identifier:
            raise ProductionContextError(
                "screening publication and start boundary belong to different cycles"
            )
        boundary_as_of = datetime.fromisoformat(str(boundary["as_of"]))
        boundary_cutoff = datetime.fromisoformat(
            str(boundary["knowledge_cutoff"])
        )
        if boundary_as_of != decision_time:
            raise ProductionContextError(
                "eligible universe, screening, and decision timestamps do not align"
            )
        if boundary_cutoff != cutoff:
            raise ProductionContextError(
                "eligible universe, screening, and evidence cutoffs do not align"
            )
        if boundary_cutoff > decision_time:
            raise ProductionContextError(
                "screening data cutoff follows the decision timestamp"
            )

        try:
            universe = self.universe_store.latest_for_decision(
                decision_timestamp=decision_time
            )
        except EligibleUniverseError as error:
            raise ProductionContextError(str(error)) from error
        if universe.identifier != publication.universe_snapshot_identifier:
            raise ProductionContextError(
                "screening publication does not use the latest certified "
                "eligible-universe publication"
            )
        if (
            universe.security_master_catalog_identifier
            != publication.security_master_catalog_identifier
        ):
            raise ProductionContextError(
                "eligible-universe and screening catalog identifiers do not match"
            )
        if (
            universe.security_master_snapshot_identifier
            != publication.security_master_snapshot_identifier
        ):
            raise ProductionContextError(
                "eligible-universe and screening security-master snapshots "
                "do not match"
            )
        if universe.knowledge_cutoff != cutoff:
            raise ProductionContextError(
                "eligible-universe and production evidence cutoffs do not match"
            )
        if (
            _text(
                boundary.get("catalog_identifier"),
                field_name="screening catalog identifier",
            )
            != universe.security_master_catalog_identifier
        ):
            raise ProductionContextError(
                "screening start boundary does not match the certified catalog"
            )
        if (
            _text(
                boundary.get("security_master_snapshot_identifier"),
                field_name="screening security-master snapshot identifier",
            )
            != universe.security_master_snapshot_identifier
        ):
            raise ProductionContextError(
                "screening start boundary does not match the certified "
                "security-master snapshot"
            )
        if (
            _text(
                boundary.get("universe_snapshot_identifier"),
                field_name="screening universe snapshot identifier",
            )
            != universe.identifier
        ):
            raise ProductionContextError(
                "screening start boundary does not match the certified universe"
            )
        if (
            _text(
                boundary.get("policy_version"),
                field_name="screening universe policy version",
            )
            != universe.policy_version
        ):
            raise ProductionContextError(
                "screening universe policy version does not match certification"
            )

        candidates = tuple(
            candidate_from_payload(payload)
            for payload in publication.candidate_payloads
        )
        candidate_instrument_ids = tuple(
            item.instrument.instrument_id for item in candidates
        )
        excluded_instrument_ids = tuple(
            _text(
                dict(item).get("instrument_identifier"),
                field_name="excluded instrument identifier",
            )
            for item in publication.exclusions
        )
        screened_instrument_ids = (
            candidate_instrument_ids + excluded_instrument_ids
        )
        if len(screened_instrument_ids) != len(set(screened_instrument_ids)):
            raise ProductionContextError(
                "screening publication contains duplicate instrument coverage"
            )
        if set(screened_instrument_ids) != set(
            universe.eligible_instrument_identifiers
        ):
            missing = sorted(
                set(universe.eligible_instrument_identifiers)
                - set(screened_instrument_ids)
            )
            extra = sorted(
                set(screened_instrument_ids)
                - set(universe.eligible_instrument_identifiers)
            )
            raise ProductionContextError(
                "screening coverage does not reconcile the certified eligible "
                f"universe: missing={missing} extra={extra}"
            )
        if len(screened_instrument_ids) != publication.eligible_instrument_count:
            raise ProductionContextError(
                "screening instrument coverage does not match the publication count"
            )

        qualified_identifiers = set(base_context.manifest.candidate_identifiers)
        expanded_candidates = tuple(
            item
            for item in candidates
            if item.identifier in qualified_identifiers
            and item.instrument.asset_class in EXPANSION_ASSET_CLASSES
        )
        packets = self.asset_evidence_store.packets_for_cycle(
            publication.cycle_identifier,
            as_of=decision_time,
        )
        packet_by_candidate = {
            item.candidate_identifier: item for item in packets
        }
        if len(packet_by_candidate) != len(packets):
            raise ProductionContextError(
                "asset-specific evidence contains duplicate candidate coverage"
            )
        expected_packet_ids = {item.identifier for item in expanded_candidates}
        if set(packet_by_candidate) != expected_packet_ids:
            missing = sorted(expected_packet_ids - set(packet_by_candidate))
            extra = sorted(set(packet_by_candidate) - expected_packet_ids)
            raise ProductionContextError(
                "asset-specific evidence must exactly match qualified expanded "
                f"candidates: missing={missing} extra={extra}"
            )
        for candidate in expanded_candidates:
            packet = packet_by_candidate[candidate.identifier]
            try:
                packet.require_match(
                    screening_cycle_identifier=publication.cycle_identifier,
                    candidate_identifier=candidate.identifier,
                    instrument_identifier=candidate.instrument.instrument_id,
                    asset_class=candidate.instrument.asset_class,
                    as_of=decision_time,
                    knowledge_cutoff=cutoff,
                )
            except MultiAssetEvidenceError as error:
                raise ProductionContextError(str(error)) from error

        packet_evidence_identifiers = tuple(
            dict.fromkeys(
                identifier
                for packet in packets
                for identifier in (
                    packet.identifier,
                    packet.asset_class_approval_identifier,
                    *packet.provider_certification_identifiers,
                    *packet.evidence_identifiers,
                    *packet.originating_fact_identifiers,
                )
            )
        )
        packet_source_versions = tuple(
            sorted({pair for packet in packets for pair in packet.source_versions})
        )
        packet_model_versions = tuple(
            sorted({pair for packet in packets for pair in packet.model_versions})
        )
        manifest = replace(
            base_context.manifest,
            evidence_identifiers=tuple(
                dict.fromkeys(
                    base_context.manifest.evidence_identifiers
                    + (
                        universe.identifier,
                        universe.certification_identifier,
                    )
                    + packet_evidence_identifiers
                )
            ),
            source_versions=_merge_versions(
                base_context.manifest.source_versions,
                universe.source_versions,
                packet_source_versions,
                field_name="source_versions",
            ),
            model_versions=_merge_versions(
                base_context.manifest.model_versions,
                universe.model_versions,
                packet_model_versions,
                (
                    ("eligible_universe_policy", universe.policy_version),
                    ("investment_process", self.process_version),
                ),
                field_name="model_versions",
            ),
        )
        specialist_contexts = tuple(
            replace(
                context,
                asset_valuation=(
                    context.asset_valuation
                    if context.candidate_identifier not in packet_by_candidate
                    else _asset_valuation_context(
                        packet_by_candidate[context.candidate_identifier]
                    )
                ),
            )
            for context in base_context.specialist_contexts
        )
        return ProductionCanonicalCIOContext(
            identifier=base_context.identifier,
            screening_cycle_identifier=(
                base_context.screening_cycle_identifier
            ),
            opportunity_context=base_context.opportunity_context,
            specialist_contexts=specialist_contexts,
            portfolio=base_context.portfolio,
            code_version=base_context.code_version,
            manifest=manifest,
            knowledge_cutoff=cutoff,
            process_version=self.process_version,
            eligible_universe_publication_identifier=universe.identifier,
        )


def build_production_context_provider(
    *,
    eligible_universe_database: str | Path | None = None,
    screening_database: str | Path | None = None,
    portfolio_database: str | Path | None = None,
    context_database: str | Path | None = None,
    asset_evidence_database: str | Path | None = None,
    portfolio_code: str | None = None,
    process_version: str | None = None,
    code_version: str | None = None,
) -> RepositoryProductionCanonicalCIOContextProvider:
    """Build the configured production adapter without external application code."""

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return RepositoryProductionCanonicalCIOContextProvider(
        universe_store=SQLiteCertifiedEligibleUniverseStore(
            eligible_universe_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_ELIGIBLE_UNIVERSE_DATABASE"
            )
            or data_dir / "eligible_universe.db"
        ),
        screening_store=SQLiteFullUniverseScreeningStore(
            screening_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
            )
            or data_dir / "full_universe_screening.db"
        ),
        portfolio_store=SQLiteCanonicalPortfolioStore(
            portfolio_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE"
            )
            or data_dir / "canonical_portfolio.db"
        ),
        context_store=SQLiteProductionContextStore(
            context_database
            or os.getenv("CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE")
            or data_dir / "production_context.db"
        ),
        asset_evidence_store=SQLiteAssetSpecificEvidenceStore(
            asset_evidence_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_ASSET_SPECIFIC_EVIDENCE_DATABASE"
            )
            or data_dir / "asset_specific_evidence.db"
        ),
        portfolio_code=portfolio_code
        or os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE")
        or "COMPOUNDING",
        process_version=process_version
        or os.getenv("CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION")
        or "capital-intelligence-investment-process.v1",
        code_version=code_version,
    )


__all__ = [
    "RepositoryProductionCanonicalCIOContextProvider",
    "build_production_context_provider",
]
