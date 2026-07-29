from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if old not in source:
        raise RuntimeError(f"expected materialization anchor missing in {path}: {old[:120]!r}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "cio/__init__.py",
    "from typing import Any\n\nfrom cio.committee import IndependentSpecialistPacket, SpecialistAnalysis\n",
    "from typing import Any\n\nfrom cio.historical_learning import (\n"
    "    HistoricalLearningContext,\n"
    "    HistoricalLearningResolver,\n"
    "    HistoricalLearningStatus,\n"
    ")\n"
    "from cio.committee import IndependentSpecialistPacket, SpecialistAnalysis\n",
)
replace_once(
    "cio/__init__.py",
    '    "EvidenceQuality",\n    "IndependentSpecialistPacket",\n',
    '    "EvidenceQuality",\n'
    '    "HistoricalLearningContext",\n'
    '    "HistoricalLearningResolver",\n'
    '    "HistoricalLearningStatus",\n'
    '    "IndependentSpecialistPacket",\n',
)

replace_once(
    "cio/committee.py",
    "from cio.models import (\n",
    "from cio.historical_learning import HistoricalLearningContext\n"
    "from cio.models import (\n",
)
replace_once(
    "cio/committee.py",
    "    candidate_identifier: str\n    analyses: tuple[SpecialistAnalysis, ...]\n",
    "    candidate_identifier: str\n"
    "    analyses: tuple[SpecialistAnalysis, ...]\n"
    "    historical_learning: HistoricalLearningContext | None = None\n",
)
replace_once(
    "cio/committee.py",
    "        if any(\n"
    "            item.candidate_identifier != self.candidate_identifier\n"
    "            for item in self.analyses\n"
    "        ):\n"
    "            raise ValueError(\n"
    "                \"all specialist analyses must reference the packet candidate\"\n"
    "            )\n\n"
    "    def for_role(self, role: SpecialistRole) -> SpecialistAnalysis:\n",
    "        if any(\n"
    "            item.candidate_identifier != self.candidate_identifier\n"
    "            for item in self.analyses\n"
    "        ):\n"
    "            raise ValueError(\n"
    "                \"all specialist analyses must reference the packet candidate\"\n"
    "            )\n"
    "        completed_at = max(item.completed_at for item in self.analyses)\n"
    "        historical_learning = self.historical_learning\n"
    "        if historical_learning is None:\n"
    "            historical_learning = HistoricalLearningContext.not_applicable(\n"
    "                candidate_identifier=self.candidate_identifier,\n"
    "                as_of=completed_at,\n"
    "                reason=(\n"
    "                    \"Direct specialist-packet construction did not supply a governed \"\n"
    "                    \"historical-learning context.\"\n"
    "                ),\n"
    "            )\n"
    "        if not isinstance(historical_learning, HistoricalLearningContext):\n"
    "            raise TypeError(\"historical_learning must be a HistoricalLearningContext\")\n"
    "        historical_learning.validate_for(\n"
    "            self.candidate_identifier,\n"
    "            completed_at=completed_at,\n"
    "        )\n"
    "        object.__setattr__(self, \"historical_learning\", historical_learning)\n\n"
    "    def for_role(self, role: SpecialistRole) -> SpecialistAnalysis:\n",
)

replace_once(
    "committee/specialists.py",
    "    EvidenceDependency,\n    IndependentSpecialistPacket,\n",
    "    EvidenceDependency,\n"
    "    HistoricalLearningContext,\n"
    "    IndependentSpecialistPacket,\n",
)
replace_once(
    "committee/specialists.py",
    "    company: CompanyAnalysis | None = None\n"
    "    asset_valuation: AssetValuationSpecialistContext | None = None\n",
    "    company: CompanyAnalysis | None = None\n"
    "    asset_valuation: AssetValuationSpecialistContext | None = None\n"
    "    historical_learning: HistoricalLearningContext | None = None\n",
)
replace_once(
    "committee/specialists.py",
    "        if (\n"
    "            self.asset_valuation is not None\n"
    "            and self.asset_valuation.as_of > self.analysis_completed_at\n"
    "        ):\n"
    "            raise ValueError(\n"
    "                \"asset valuation analysis cannot be newer than completion time\"\n"
    "            )\n\n\n"
    "@dataclass(frozen=True, slots=True)\n"
    "class SpecialistGovernancePolicy:\n",
    "        if (\n"
    "            self.asset_valuation is not None\n"
    "            and self.asset_valuation.as_of > self.analysis_completed_at\n"
    "        ):\n"
    "            raise ValueError(\n"
    "                \"asset valuation analysis cannot be newer than completion time\"\n"
    "            )\n"
    "        if self.historical_learning is not None:\n"
    "            if not isinstance(self.historical_learning, HistoricalLearningContext):\n"
    "                raise TypeError(\n"
    "                    \"historical_learning must be a HistoricalLearningContext or None\"\n"
    "                )\n"
    "            self.historical_learning.validate_for(\n"
    "                self.candidate_identifier,\n"
    "                completed_at=self.analysis_completed_at,\n"
    "            )\n\n\n"
    "@dataclass(frozen=True, slots=True)\n"
    "class SpecialistGovernancePolicy:\n",
)
replace_once(
    "committee/specialists.py",
    "        return IndependentSpecialistPacket(\n"
    "            candidate_identifier=candidate.identifier,\n"
    "            analyses=analyses,\n"
    "        )\n",
    "        return IndependentSpecialistPacket(\n"
    "            candidate_identifier=candidate.identifier,\n"
    "            analyses=analyses,\n"
    "            historical_learning=context.historical_learning,\n"
    "        )\n",
)

replace_once(
    "application/cio_cycle.py",
    "    ChiefInvestmentOfficer,\n"
    "    IndependentSpecialistPacket,\n"
    "    PriorDecisionContext,\n",
    "    ChiefInvestmentOfficer,\n"
    "    HistoricalLearningContext,\n"
    "    HistoricalLearningResolver,\n"
    "    IndependentSpecialistPacket,\n"
    "    PriorDecisionContext,\n",
)
replace_once(
    "application/cio_cycle.py",
    "        briefing_builder: DailyCIOBriefingBuilder | None = None,\n"
    "        journal: SQLiteCIOJournal | None = None,\n"
    "    ) -> None:\n",
    "        briefing_builder: DailyCIOBriefingBuilder | None = None,\n"
    "        journal: SQLiteCIOJournal | None = None,\n"
    "        historical_learning_resolver: HistoricalLearningResolver | None = None,\n"
    "    ) -> None:\n",
)
replace_once(
    "application/cio_cycle.py",
    "        self.briefing_builder = briefing_builder or DailyCIOBriefingBuilder()\n"
    "        self.journal = journal\n",
    "        self.briefing_builder = briefing_builder or DailyCIOBriefingBuilder()\n"
    "        self.journal = journal\n"
    "        self.historical_learning_resolver = (\n"
    "            historical_learning_resolver or HistoricalLearningResolver.from_environment()\n"
    "        )\n",
)
replace_once(
    "application/cio_cycle.py",
    "            portfolio_context = self._preview_portfolio(\n"
    "                candidate=candidate,\n"
    "                rank=ranked.rank,\n"
    "                portfolio=portfolio,\n"
    "            )\n"
    "            specialist_context = CandidateSpecialistContext(\n",
    "            portfolio_context = self._preview_portfolio(\n"
    "                candidate=candidate,\n"
    "                rank=ranked.rank,\n"
    "                portfolio=portfolio,\n"
    "            )\n"
    "            if cycle_identifier.startswith(\"historical-canonical-cycle:\"):\n"
    "                historical_learning = HistoricalLearningContext.not_applicable(\n"
    "                    candidate_identifier=candidate.identifier,\n"
    "                    as_of=base_context.analysis_completed_at,\n"
    "                    reason=(\n"
    "                        \"Historical replay cannot consume a manifest generated from its \"\n"
    "                        \"own future results.\"\n"
    "                    ),\n"
    "                )\n"
    "            else:\n"
    "                historical_learning = self.historical_learning_resolver.resolve(\n"
    "                    candidate,\n"
    "                    as_of=base_context.analysis_completed_at,\n"
    "                    macro_regime=base_context.macro.regime,\n"
    "                    market_regime=base_context.market.market_regime,\n"
    "                )\n"
    "            specialist_context = CandidateSpecialistContext(\n",
)
replace_once(
    "application/cio_cycle.py",
    "                company=base_context.company,\n"
    "                asset_valuation=base_context.asset_valuation,\n"
    "            )\n",
    "                company=base_context.company,\n"
    "                asset_valuation=base_context.asset_valuation,\n"
    "                historical_learning=historical_learning,\n"
    "            )\n",
)

replace_once(
    "cio/service.py",
    '    version: str = "cio-synthesis.v5"\n',
    '    version: str = "cio-synthesis.v6"\n',
)
replace_once(
    "cio/service.py",
    "        supported_weight = self.robust_assessor.maximum_supported_weight(\n",
    "        historical_learning = specialists.historical_learning\n"
    "        assessment_cap = round(\n"
    "            assessment_cap * historical_learning.position_size_multiplier,\n"
    "            8,\n"
    "        )\n"
    "        supported_weight = self.robust_assessor.maximum_supported_weight(\n",
)
replace_once(
    "cio/service.py",
    "        final_confidence = self._confidence(\n",
    "        if historical_learning.status.value != \"not_applicable\":\n"
    "            reason = f\"{reason} {historical_learning.summary}\"\n"
    "        final_confidence = self._confidence(\n",
)
replace_once(
    "cio/service.py",
    "        explanation = self._explanation(\n"
    "            candidate,\n"
    "            action=action,\n"
    "            reason=reason,\n"
    "            confidence=final_confidence,\n"
    "            has_dissent=dissent is not None,\n"
    "            robustness=robustness,\n"
    "            reconciliation=reconciliation,\n"
    "        )\n",
    "        opportunity_cost += (\n"
    "            \" Historical-learning control: \" + historical_learning.summary\n"
    "        )\n"
    "        explanation = self._explanation(\n"
    "            candidate,\n"
    "            action=action,\n"
    "            reason=reason,\n"
    "            confidence=final_confidence,\n"
    "            has_dissent=dissent is not None,\n"
    "            robustness=robustness,\n"
    "            reconciliation=reconciliation,\n"
    "        )\n"
    "        if historical_learning.status.value != \"not_applicable\":\n"
    "            explanation += \" Historical learning: \" + historical_learning.summary\n",
)
replace_once(
    "cio/service.py",
    "            supporting_evidence=candidate.supporting_evidence,\n",
    "            supporting_evidence=tuple(\n"
    "                dict.fromkeys(\n"
    "                    candidate.supporting_evidence\n"
    "                    + (historical_learning.summary,)\n"
    "                )\n"
    "            ),\n",
)
replace_once(
    "cio/service.py",
    "            risks=candidate.key_risks,\n",
    "            risks=tuple(\n"
    "                dict.fromkeys(candidate.key_risks + historical_learning.limitations)\n"
    "            ),\n",
)
replace_once(
    "cio/service.py",
    "            monitoring_indicators=candidate.monitoring_indicators,\n",
    "            monitoring_indicators=tuple(\n"
    "                dict.fromkeys(\n"
    "                    candidate.monitoring_indicators\n"
    "                    + (\"historical_learning_calibration\",)\n"
    "                )\n"
    "            ),\n",
)
replace_once(
    "cio/service.py",
    "        if specialists.implementation_blocks:\n"
    "            calculated = min(calculated, 0.50)\n"
    "        return round(max(0.0, min(1.0, calculated)), 6)\n",
    "        if specialists.implementation_blocks:\n"
    "            calculated = min(calculated, 0.50)\n"
    "        calculated = min(\n"
    "            calculated,\n"
    "            specialists.historical_learning.confidence_ceiling,\n"
    "        )\n"
    "        return round(max(0.0, min(1.0, calculated)), 6)\n",
)

replace_once(
    "cio/persistence.py",
    "        \"candidate_identifier\": packet.candidate_identifier,\n"
    "        \"support_ratio\": packet.support_ratio,\n",
    "        \"candidate_identifier\": packet.candidate_identifier,\n"
    "        \"historical_learning\": packet.historical_learning.as_dict(),\n"
    "        \"support_ratio\": packet.support_ratio,\n",
)

doc = Path("docs/HISTORICAL_REPLAY.md")
doc_source = doc.read_text(encoding="utf-8")
section = """

## Governed use in live committee and CIO decisions

Every live canonical specialist packet now carries a mandatory
`HistoricalLearningContext`. The resolver reads only a replay manifest that was
available by the specialist-completion timestamp and selects exact-symbol
history when sufficient, otherwise governed asset-class comparables.

Historical learning is deliberately one-way and subordinate to current
evidence:

- it may cap CIO confidence;
- it may reduce the otherwise supported target position;
- it adds limitations, provenance, sample size, support and abstention rates to
  the immutable specialist packet;
- missing or limited history is explicit rather than silently ignored;
- it cannot raise expected return, increase confidence, enlarge a position,
  create a candidate, authorize execution, or promote policy.

The historical replay itself receives a `not_applicable` context so it cannot
consume a manifest generated from future replay results. Live decisions use the
manifest under `CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR`, while the resulting
learning context is persisted with the specialist packet for later outcome and
calibration review.

Optional control:

- `CAPITAL_INTELLIGENCE_HISTORICAL_LEARNING_MINIMUM_SAMPLE`, default `6`
"""
if "## Governed use in live committee and CIO decisions" not in doc_source:
    doc.write_text(doc_source.rstrip() + section + "\n", encoding="utf-8")

Path("tests/test_governed_historical_learning.py").write_text(
    '''from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    HistoricalLearningContext,
    HistoricalLearningResolver,
    HistoricalLearningStatus,
)

UTC = timezone.utc


def _candidate(as_of: datetime) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:spy",
        as_of=as_of,
        schema_version="candidate.v1",
        instrument=CandidateInstrument(
            instrument_id="instrument:spy",
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            asset_class=CandidateAssetClass.US_ETF,
            venue="ARCX",
            country_code="US",
            average_daily_dollar_volume=1_000_000_000.0,
            data_age_hours=0.1,
            analytical_coverage=1.0,
            security_master_snapshot_identifier="security-master:now",
            security_master_record_identifiers=("security-master:spy",),
            instrument_type="etf",
        ),
        current_price=500.0,
        decision_horizon_days=365,
        base_case_return=0.10,
        bull_case_return=0.20,
        bear_case_return=-0.15,
        base_case_probability=0.50,
        bull_case_probability=0.25,
        bear_case_probability=0.25,
        estimated_fair_value=550.0,
        expected_upside=0.20,
        expected_downside=-0.15,
        probability_of_success=0.65,
        primary_catalysts=("earnings growth",),
        key_risks=("recession",),
        critical_assumptions=("growth persists",),
        invalidation_conditions=("trend breaks",),
        supporting_evidence=("current evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(0.9, 0.9, 0.9, 0.8, 0.8, 0.9),
        liquidity_score=1.0,
        transaction_cost_bps=1.0,
        slippage_bps=1.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("trend",),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=("evidence:current",),
        model_versions=("model:v1",),
    )


def _manifest(generated_at: datetime) -> dict[str, object]:
    decisions = []
    for month in range(1, 7):
        decisions.append(
            {
                "cutoff": f"2026-{month:02d}-28T23:59:59+00:00",
                "state": "completed",
                "canonical_cio_invoked": True,
                "decisions": [
                    {
                        "candidate_identifier": f"historical:2026-{month:02d}-28:SPY",
                        "action": "buy" if month < 5 else "watch",
                        "final_confidence": 0.80,
                        "recommended_position_weight": 0.10,
                    }
                ],
            }
        )
    return {
        "schema_version": "canonical-historical-replay.v1",
        "generated_at": generated_at.isoformat(),
        "strict_only": False,
        "decisions": decisions,
    }


def test_resolver_attaches_restrictive_governed_context(tmp_path) -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    manifest = tmp_path / "latest-canonical-replay.json"
    manifest.write_text(
        json.dumps(_manifest(as_of - timedelta(hours=1))),
        encoding="utf-8",
    )
    context = HistoricalLearningResolver(manifest).resolve(
        _candidate(as_of),
        as_of=as_of,
        macro_regime="mixed",
        market_regime="positive_trend",
    )

    assert context.status is HistoricalLearningStatus.AVAILABLE
    assert context.sample_size == 6
    assert context.exact_symbol_sample_size == 6
    assert 0.0 < context.position_size_multiplier <= 1.0
    assert 0.0 < context.confidence_ceiling <= 1.0
    assert context.subordinate_to_current_evidence is True
    assert context.may_increase_expected_return is False
    assert context.may_increase_confidence is False
    assert context.may_increase_position_size is False
    assert context.execution_authorized is False
    assert context.policy_promotion_authorized is False


def test_future_manifest_is_rejected(tmp_path) -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    manifest = tmp_path / "latest-canonical-replay.json"
    manifest.write_text(
        json.dumps(_manifest(as_of + timedelta(seconds=1))),
        encoding="utf-8",
    )
    context = HistoricalLearningResolver(manifest).resolve(
        _candidate(as_of),
        as_of=as_of,
        macro_regime="mixed",
        market_regime="positive_trend",
    )

    assert context.status is HistoricalLearningStatus.UNAVAILABLE
    assert context.position_size_multiplier == 0.50
    assert "after the decision timestamp" in context.summary


def test_historical_learning_cannot_grant_positive_authority() -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot strengthen"):
        HistoricalLearningContext(
            candidate_identifier="candidate:spy",
            as_of=as_of,
            status=HistoricalLearningStatus.AVAILABLE,
            source_manifest_identifier="manifest:1",
            sample_size=12,
            exact_symbol_sample_size=12,
            strict_replay=True,
            support_rate=1.0,
            abstention_rate=0.0,
            median_historical_confidence=0.9,
            median_historical_position_weight=0.1,
            position_size_multiplier=1.0,
            confidence_ceiling=1.0,
            summary="invalid authority test",
            limitations=(),
            evidence_identifiers=("manifest:1",),
            may_increase_position_size=True,
        )


def test_live_cycle_and_cio_apply_historical_controls() -> None:
    cycle_source = open("application/cio_cycle.py", encoding="utf-8").read()
    cio_source = open("cio/service.py", encoding="utf-8").read()
    persistence_source = open("cio/persistence.py", encoding="utf-8").read()

    assert "historical_learning_resolver.resolve" in cycle_source
    assert "historical_learning=historical_learning" in cycle_source
    assert "assessment_cap * historical_learning.position_size_multiplier" in cio_source
    assert "historical_learning.confidence_ceiling" in cio_source
    assert '"historical_learning": packet.historical_learning.as_dict()' in persistence_source
''',
    encoding="utf-8",
)
