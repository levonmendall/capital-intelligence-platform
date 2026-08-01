"""Resolve integration defects exposed by the first remediation validation run."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected patch anchor is missing in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_historical_feature_keys() -> None:
    replace_once(
        "historical_replay/canonical.py",
        '        features = market_features(records, cutoff=cutoff_text)\n',
        '        raw_features = market_features(records, cutoff=cutoff_text)\n'
        '        features = {_symbol(symbol): value for symbol, value in raw_features.items()}\n',
    )


def patch_candidate_derived_authority() -> None:
    marker = '''    def assess(\n        self,\n        instrument: CandidateInstrument,\n        *,\n        evaluated_at: datetime,\n    ) -> AssetClassScopeAssessment:\n'''
    insertion = '''    @classmethod\n    def from_candidates(\n        cls,\n        candidates: tuple[object, ...],\n        *,\n        authority_identifier: str,\n        research_only: bool = False,\n    ) -> "BoundedPilotCapabilityAuthority":\n        identifier = str(authority_identifier).strip()\n        if not identifier:\n            raise ValueError("authority_identifier cannot be empty")\n        capabilities: list[BoundedPilotInstrumentCapability] = []\n        for value in candidates:\n            instrument = getattr(value, "instrument", value)\n            if not isinstance(instrument, CandidateInstrument):\n                raise TypeError("candidates must contain candidate records or instruments")\n            governed = instrument.economic_exposure_class or instrument.asset_class\n            capabilities.append(\n                BoundedPilotInstrumentCapability(\n                    instrument_identifier=instrument.instrument_id,\n                    symbol=instrument.symbol,\n                    execution_asset_class=instrument.asset_class,\n                    governed_asset_class=governed,\n                    venue=instrument.venue,\n                    country_code=instrument.country_code,\n                    instrument_type=instrument.instrument_type,\n                    approval_identifier=(\n                        f"screening-policy:{identifier}:{instrument.instrument_id}"\n                    ),\n                )\n            )\n        return cls(\n            tuple(capabilities),\n            universe_identifier=identifier,\n            research_only=research_only,\n        )\n\n'''
    replace_once(
        "governance/bounded_pilot_scope.py",
        marker,
        insertion + marker,
    )


def patch_production_executor() -> None:
    replace_once(
        "application/production_context_contract.py",
        'from cio.persistence import CIOJournalEventType\nfrom screening import candidate_from_payload\n',
        'from application.cio_cycle import CanonicalCIOCycle\n'
        'from cio import RecommendationUniversePolicy\n'
        'from cio.persistence import CIOJournalEventType\n'
        'from governance.bounded_pilot_scope import BoundedPilotCapabilityAuthority\n'
        'from opportunity import OpportunityEngine\n'
        'from screening import candidate_from_payload\n',
    )

    anchor = '''        governed_context = (\n            isinstance(context, ProductionCanonicalCIOContext)\n            and context.eligible_universe_publication_identifier != "unknown"\n            and context.process_version != "unknown"\n        )\n        if governed_context:\n'''
    replacement = '''        governed_context = (\n            isinstance(context, ProductionCanonicalCIOContext)\n            and context.eligible_universe_publication_identifier != "unknown"\n            and context.process_version != "unknown"\n        )\n        cycle = self.cycle\n        if governed_context:\n            existing_engine = self.cycle.opportunity_engine\n            capability_authority = BoundedPilotCapabilityAuthority.from_candidates(\n                candidates,\n                authority_identifier=publication.universe_snapshot_identifier,\n            )\n            runtime_engine = OpportunityEngine(\n                universe_policy=RecommendationUniversePolicy(\n                    asset_class_authority=capability_authority\n                ),\n                qualification_policy=existing_engine.policy,\n                robustness_policy=existing_engine.robust_assessor.policy,\n                policy_matrix=existing_engine.policy_matrix,\n            )\n            cycle = CanonicalCIOCycle(\n                opportunity_engine=runtime_engine,\n                specialist_service=self.cycle.specialist_service,\n                cio=self.cycle.cio,\n                construction_engine=self.cycle.construction_engine,\n                briefing_builder=self.cycle.briefing_builder,\n                journal=self.cycle.journal,\n                historical_learning_resolver=(\n                    self.cycle.historical_learning_resolver\n                ),\n            )\n        if governed_context:\n'''
    replace_once("application/production_context_contract.py", anchor, replacement)

    substitutions = (
        (
            '            runtime_queue = self.cycle.opportunity_engine.build_queue(\n',
            '            runtime_queue = cycle.opportunity_engine.build_queue(\n',
        ),
        (
            '        if self.cycle.journal is not None:\n'
            '            prior_decision_contexts = self.cycle.journal.prior_decision_contexts(\n',
            '        if cycle.journal is not None:\n'
            '            prior_decision_contexts = cycle.journal.prior_decision_contexts(\n',
        ),
        (
            '            active_theses = self.cycle.journal.active_theses(\n',
            '            active_theses = cycle.journal.active_theses(\n',
        ),
        ('        result = self.cycle.run(\n', '        result = cycle.run(\n'),
        ('        journal = self.cycle.journal\n', '        journal = cycle.journal\n'),
        (
            '                        self.cycle.opportunity_engine.policy.minimum_evidence_score\n',
            '                        cycle.opportunity_engine.policy.minimum_evidence_score\n',
        ),
        (
            '                        self.cycle.opportunity_engine.policy.minimum_evidence_dimension\n',
            '                        cycle.opportunity_engine.policy.minimum_evidence_dimension\n',
        ),
    )
    for old, new in substitutions:
        replace_once("application/production_context_contract.py", old, new)


def main() -> None:
    patch_historical_feature_keys()
    patch_candidate_derived_authority()
    patch_production_executor()


if __name__ == "__main__":
    main()
