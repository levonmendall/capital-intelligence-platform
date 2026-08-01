"""Executable repository production-context assembly.

A screening publication may be recorded after its point-in-time evidence cutoff.
The cutoff governs the information inside the publication, while ``published_at``
is the append time of the completed artifact.  This runtime provider preserves
that distinction while reusing the append-only evidence contracts and serializers
from :mod:`application.production_context`.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from application.cio_cycle import CandidateCycleContext, CyclePortfolioState
from application.production_cio import ProductionCanonicalCIOContext
from application.production_context import (
    ProductionContextError,
    RepositoryProductionCanonicalCIOContextProvider as _StoredContextProvider,
    SQLiteProductionContextStore,
    _aware,
    _text,
)
from cio import CandidateAssetClass
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunitySetContext,
)
from portfolio.production_scenarios import build_governed_portfolio_scenario_set
from portfolio.state import SQLiteCanonicalPortfolioStore
from screening import (
    ScreeningEventType,
    SQLiteFullUniverseScreeningStore,
    candidate_from_payload,
)


class RepositoryProductionCanonicalCIOContextProvider(_StoredContextProvider):
    """Assemble the runnable context from exact persisted authorities.

    ``published_at`` is intentionally not compared with ``knowledge_cutoff``.
    Publication completion necessarily follows the evidence cutoff in normal
    operations; point-in-time integrity is enforced by the cycle boundary and
    every governed evidence record instead.
    """

    def load_context(
        self,
        *,
        as_of: datetime,
    ) -> ProductionCanonicalCIOContext:
        decision_time = _aware(as_of, field_name="as_of")
        self.screening_store.verify_integrity()
        self.portfolio_store.verify_integrity()
        self.context_store.verify_integrity()

        evidence = self.context_store.snapshot_for_as_of(
            portfolio_code=self.portfolio_code,
            as_of=decision_time,
        )
        if evidence is None:
            raise ProductionContextError(
                "certified production context evidence is unavailable "
                "for the decision timestamp"
            )
        publication = self.screening_store.publication(
            evidence.screening_cycle_identifier
        )
        if publication is None:
            raise ProductionContextError(
                "production context requires a persisted screening publication"
            )
        cycle_events = self.screening_store.events(
            evidence.screening_cycle_identifier,
            event_type=ScreeningEventType.CYCLE_STARTED,
        )
        if len(cycle_events) != 1:
            raise ProductionContextError(
                "screening cycle must contain exactly one start boundary"
            )
        cycle_boundary = cycle_events[0].payload
        screening_as_of = datetime.fromisoformat(str(cycle_boundary["as_of"]))
        screening_cutoff = datetime.fromisoformat(
            str(cycle_boundary["knowledge_cutoff"])
        )
        if screening_as_of != decision_time or evidence.as_of != decision_time:
            raise ProductionContextError(
                "screening, evidence, and decision timestamps do not match"
            )
        if screening_cutoff != evidence.knowledge_cutoff:
            raise ProductionContextError(
                "screening and production evidence knowledge cutoffs do not match"
            )
        if (
            publication.screened_instrument_count
            != publication.eligible_instrument_count
        ):
            raise ProductionContextError(
                "production context cannot consume incomplete screening coverage"
            )

        candidates = tuple(
            candidate_from_payload(payload)
            for payload in publication.candidate_payloads
        )
        candidate_map = {item.identifier: item for item in candidates}
        if len(candidate_map) != len(candidates):
            raise ProductionContextError(
                "screening publication contains duplicate candidate identifiers"
            )
        if any(item.as_of != decision_time for item in candidates):
            raise ProductionContextError(
                "screened candidates do not share the decision timestamp"
            )
        ranked_payloads = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("ranked", ())
        )
        qualified_ids = tuple(
            _text(
                item.get("candidate_identifier"),
                field_name="qualified candidate identifier",
            )
            for item in ranked_payloads
        )
        if len(qualified_ids) != len(set(qualified_ids)):
            raise ProductionContextError(
                "screening publication contains duplicate qualified candidates"
            )
        if not set(qualified_ids).issubset(candidate_map):
            raise ProductionContextError(
                "screening opportunity queue references unknown candidates"
            )

        candidate_evidence = {
            item.candidate_identifier: item for item in evidence.candidate_evidence
        }
        if set(candidate_evidence) != set(qualified_ids):
            missing = sorted(set(qualified_ids) - set(candidate_evidence))
            extra = sorted(set(candidate_evidence) - set(qualified_ids))
            raise ProductionContextError(
                "candidate context coverage must exactly match qualified "
                f"screening candidates: missing={missing} extra={extra}"
            )
        for candidate_identifier in qualified_ids:
            candidate = candidate_map[candidate_identifier]
            governed = candidate_evidence[candidate_identifier]
            if governed.symbol != candidate.instrument.symbol:
                raise ProductionContextError(
                    f"candidate context symbol does not match {candidate_identifier}"
                )
            if (
                candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY
                and governed.company is None
            ):
                raise ProductionContextError(
                    f"equity candidate {candidate_identifier} is missing governed "
                    "fundamental and valuation analysis"
                )

        portfolio_snapshot = self._portfolio_snapshot(decision_time)
        holding_context = {
            item.symbol: item for item in evidence.holding_evidence
        }
        portfolio_symbols = {item.symbol for item in portfolio_snapshot.positions}
        if set(holding_context) != portfolio_symbols:
            missing = sorted(portfolio_symbols - set(holding_context))
            extra = sorted(set(holding_context) - portfolio_symbols)
            raise ProductionContextError(
                "holding context coverage must exactly match canonical holdings: "
                f"missing={missing} extra={extra}"
            )
        if portfolio_snapshot.nav <= 0.0:
            raise ProductionContextError("canonical portfolio NAV must be positive")
        cash_weight = round(
            portfolio_snapshot.cash_amount / portfolio_snapshot.nav,
            8,
        )
        if cash_weight <= 0.0:
            raise ProductionContextError(
                "canonical portfolio must retain a positive cash alternative"
            )

        positions = tuple(
            self._portfolio_asset(
                position=position,
                portfolio_value=portfolio_snapshot.nav,
                evidence=holding_context[position.symbol],
            )
            for position in portfolio_snapshot.positions
        )
        specialist_contexts = tuple(
            CandidateCycleContext(
                candidate_identifier=candidate_identifier,
                analysis_completed_at=(
                    candidate_evidence[candidate_identifier].analysis_completed_at
                ),
                macro=candidate_evidence[candidate_identifier].macro,
                market=candidate_evidence[candidate_identifier].market,
                forecast=candidate_evidence[candidate_identifier].forecast,
                company=candidate_evidence[candidate_identifier].company,
                asset_valuation=(
                    candidate_evidence[candidate_identifier].asset_valuation
                ),
            )
            for candidate_identifier in qualified_ids
        )
        exposure_profiles = tuple(
            candidate_evidence[candidate_identifier].exposure_profile
            for candidate_identifier in qualified_ids
        )
        scenario_set = (
            None
            if not candidates
            else build_governed_portfolio_scenario_set(
                identifier=f"portfolio-scenarios:{publication.identifier}",
                source_identifier=publication.identifier,
                as_of=decision_time,
                knowledge_cutoff=evidence.knowledge_cutoff,
                candidates=candidates,
                cash_expected_return=evidence.cash_expected_return,
            )
        )
        portfolio = CyclePortfolioState(
            identifier=f"cycle-portfolio:{portfolio_snapshot.identifier}",
            as_of=decision_time,
            portfolio_value=portfolio_snapshot.nav,
            cash_weight=cash_weight,
            cash_expected_return=evidence.cash_expected_return,
            positions=positions,
            exposure_profiles=exposure_profiles,
            scenario_set=scenario_set,
        )

        alternatives: list[AlternativeUse] = [
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=evidence.cash_expected_return,
                implementation_cost_return=0.0,
                evidence_quality=evidence.cash_evidence_quality,
                liquidity_score=evidence.cash_liquidity_score,
                current_weight=cash_weight,
            )
        ]
        alternatives.extend(
            AlternativeUse(
                identifier=f"holding:{position.symbol}",
                kind=AlternativeKind.CURRENT_HOLDING,
                expected_return=holding_context[position.symbol].expected_return,
                implementation_cost_return=(
                    holding_context[position.symbol].implementation_cost_return
                ),
                evidence_quality=holding_context[
                    position.symbol
                ].evidence_quality,
                liquidity_score=holding_context[position.symbol].liquidity_score,
                current_weight=round(
                    position.market_value / portfolio_snapshot.nav,
                    8,
                ),
            )
            for position in portfolio_snapshot.positions
        )
        raw_candidate_alternatives = publication.opportunity_queue_payload.get(
            "candidate_alternative_identifiers"
        )
        if raw_candidate_alternatives is None:
            candidate_alternative_ids = tuple(
                identifier
                for identifier in qualified_ids
                if candidate_map[identifier].current_portfolio_weight <= 0.0
            )
        else:
            if not isinstance(raw_candidate_alternatives, (list, tuple)):
                raise ProductionContextError(
                    "persisted candidate alternative identifiers must be a sequence"
                )
            candidate_alternative_ids = tuple(
                _text(item, field_name="candidate alternative identifier")
                for item in raw_candidate_alternatives
            )
        if len(candidate_alternative_ids) != len(set(candidate_alternative_ids)):
            raise ProductionContextError(
                "persisted candidate alternative identifiers contain duplicates"
            )
        if not set(candidate_alternative_ids).issubset(candidate_map):
            raise ProductionContextError(
                "persisted candidate alternatives reference unknown candidates"
            )
        baseline_context = OpportunitySetContext(
            identifier=publication.opportunity_context_identifier,
            as_of=decision_time,
            alternatives=tuple(alternatives),
        )
        comparison_engine = OpportunityEngine()
        for candidate_identifier in candidate_alternative_ids:
            candidate = candidate_map[candidate_identifier]
            if candidate.current_portfolio_weight > 0.0:
                raise ProductionContextError(
                    "a current holding cannot be duplicated as a candidate alternative"
                )
            assessment = comparison_engine.robustness(
                candidate,
                baseline_context,
            )
            alternatives.append(
                AlternativeUse(
                    identifier=candidate_identifier,
                    kind=AlternativeKind.QUALIFIED_CANDIDATE,
                    expected_return=assessment.evidence_adjusted_return,
                    implementation_cost_return=0.0,
                    evidence_quality=1.0,
                    liquidity_score=1.0,
                    current_weight=0.0,
                )
            )
        opportunity_context = OpportunitySetContext(
            identifier=publication.opportunity_context_identifier,
            as_of=decision_time,
            alternatives=tuple(alternatives),
        )
        manifest = self._manifest(
            evidence=evidence,
            publication_identifier=publication.identifier,
            portfolio_snapshot_identifier=portfolio_snapshot.identifier,
            qualified_ids=qualified_ids,
        )
        return ProductionCanonicalCIOContext(
            identifier=f"canonical-cycle:{evidence.screening_cycle_identifier}",
            screening_cycle_identifier=evidence.screening_cycle_identifier,
            opportunity_context=opportunity_context,
            specialist_contexts=specialist_contexts,
            portfolio=portfolio,
            code_version=self.code_version,
            manifest=manifest,
        )


def build_production_context_provider(
    *,
    screening_database: str | Path | None = None,
    portfolio_database: str | Path | None = None,
    context_database: str | Path | None = None,
    portfolio_code: str | None = None,
    code_version: str | None = None,
) -> RepositoryProductionCanonicalCIOContextProvider:
    """Build the executable repository provider from paths or environment."""

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return RepositoryProductionCanonicalCIOContextProvider(
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
        portfolio_code=portfolio_code
        or os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE")
        or "COMPOUNDING",
        code_version=code_version,
    )


__all__ = [
    "RepositoryProductionCanonicalCIOContextProvider",
    "build_production_context_provider",
]
