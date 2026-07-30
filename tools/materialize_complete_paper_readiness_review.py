from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {source.count(old)}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "reporting/daily_cio.py",
    '''        if not queue.ranked:
            rejection_reasons = tuple(
                reason
                for rejected in queue.rejected
                for reason in rejected.reasons
            )
            return DailyCIOBriefing(
                identifier=f"daily-cio:{as_of.isoformat()}",
                as_of=as_of,
                status=DailyCIOStatus.NO_SUPERIOR_OPPORTUNITY,
                what_changed=(
                    "No candidate cleared the governed opportunity qualification process."
                ),
                why_it_matters=(
                    "Cash and current holdings remain preferable to the screened alternatives after evidence, cost, downside, liquidity, and opportunity-cost controls."
                ),
                opportunity_or_risk=(
                    "No superior evidence-supported use of capital is available."
                ),
                portfolio_decision="No portfolio action is required.",
                confidence=None,
                evidence_that_changes_conclusion=(
                    rejection_reasons
                    or (
                        "A candidate must clear the return, evidence, liquidity, cost, downside, and opportunity thresholds",
                    )
                ),
                material_developments=(
                    "The governed review queue is empty",
                ),
                thesis_identifiers=tuple(
                    item.identifier for item in theses
                ),
            )
''',
    '''        if not queue.ranked:
            rejection_reasons = tuple(
                reason
                for rejected in queue.rejected
                for reason in rejected.reasons
            )
            evidence_limited_terms = (
                "evidence",
                "data",
                "stale",
                "missing",
                "incomplete",
                "coverage",
                "unavailable",
                "uncertified",
                "unapproved",
            )
            evidence_incomplete = not queue.rejected or any(
                term in reason.lower()
                for reason in rejection_reasons
                for term in evidence_limited_terms
            )
            if evidence_incomplete:
                return DailyCIOBriefing(
                    identifier=f"daily-cio:{as_of.isoformat()}",
                    as_of=as_of,
                    status=DailyCIOStatus.INSUFFICIENT_EVIDENCE,
                    what_changed=(
                        "The governed review did not produce a complete candidate evidence set."
                    ),
                    why_it_matters=(
                        "The CIO cannot conclude that cash or current holdings are superior when one or more eligible instruments were not supported by decision-complete evidence."
                    ),
                    opportunity_or_risk=(
                        "No portfolio action is authorized until comparative candidate evidence is complete."
                    ),
                    portfolio_decision="No portfolio action is permitted.",
                    confidence=None,
                    evidence_that_changes_conclusion=(
                        rejection_reasons
                        or (
                            "Produce certified candidate evidence for the complete governed review set",
                        )
                    ),
                    material_developments=(
                        "The comparative opportunity set is incomplete",
                    ),
                    thesis_identifiers=tuple(
                        item.identifier for item in theses
                    ),
                )
            return DailyCIOBriefing(
                identifier=f"daily-cio:{as_of.isoformat()}",
                as_of=as_of,
                status=DailyCIOStatus.NO_SUPERIOR_OPPORTUNITY,
                what_changed=(
                    "No candidate cleared the governed opportunity qualification process."
                ),
                why_it_matters=(
                    "Cash and current holdings remain preferable to the screened alternatives after evidence, cost, downside, liquidity, and opportunity-cost controls."
                ),
                opportunity_or_risk=(
                    "No superior evidence-supported use of capital is available."
                ),
                portfolio_decision="No portfolio action is required.",
                confidence=None,
                evidence_that_changes_conclusion=rejection_reasons,
                material_developments=(
                    "The governed review queue contains no qualified opportunity",
                ),
                thesis_identifiers=tuple(
                    item.identifier for item in theses
                ),
            )
''',
)

replace_once(
    "cio/service.py",
    "        assessment_weight = supported_weight or assessment_cap\n",
    '''        assessment_weight = (
            supported_weight
            if supported_weight > 0.0
            else min(
                self.robust_assessor.policy.minimum_reference_weight,
                assessment_cap,
            )
        )
''',
)

replace_once(
    "run_scheduler.py",
    "import logging\nimport time\n",
    "import logging\nimport os\nimport time\n",
)
replace_once(
    "run_scheduler.py",
    "from operations import OperationalSettings, WorkerHeartbeatStore, configure_logging\nfrom screening import SQLiteFullUniverseScreeningStore\n",
    '''from operations import OperationalSettings, WorkerHeartbeatStore, configure_logging
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
)
from portfolio.construction_api import PortfolioConstructionPolicy
from screening import SQLiteFullUniverseScreeningStore
''',
)
replace_once(
    "run_scheduler.py",
    '''def build_worker(settings: ApiSettings) -> ScheduledCanonicalCIOWorker:
    """Build the only active scheduled investment-decision authority."""
''',
    '''def _paper_pilot_construction_policy() -> PortfolioConstructionPolicy:
    """Use one policy boundary for CIO construction and paper execution."""

    universe_path = os.getenv(
        "CAPITAL_INTELLIGENCE_FREE_PAPER_PILOT_UNIVERSE",
        str(DEFAULT_UNIVERSE_PATH),
    )
    universe = load_free_paper_pilot_universe(universe_path)
    base = PortfolioConstructionPolicy()
    return replace(
        base,
        version=f"{base.version}+{universe.identifier}",
        minimum_cash_weight=universe.minimum_cash_weight,
        maximum_position_weight=min(
            base.maximum_position_weight,
            universe.maximum_single_instrument_weight,
        ),
        maximum_turnover=universe.maximum_batch_turnover,
    )


def build_worker(settings: ApiSettings) -> ScheduledCanonicalCIOWorker:
    """Build the only active scheduled investment-decision authority."""
''',
)
replace_once(
    "run_scheduler.py",
    "        cycle=CanonicalCIOCycle(journal=journal),\n",
    '''        cycle=CanonicalCIOCycle(
            journal=journal,
            construction_policy=_paper_pilot_construction_policy(),
        ),
''',
)

replace_once(
    "cio_pending_transactions.py",
    '''_GOVERNED_NO_ACTION_STATUSES = frozenset(
    {
        "no_superior_opportunity",
        "insufficient_evidence",
        "implementation_blocked",
    }
)
''',
    '''_GOVERNED_NO_ACTION_STATUSES = frozenset(
    {
        "no_superior_opportunity",
        "insufficient_evidence",
        "implementation_blocked",
    }
)
_COMPARATIVE_NO_ACTION_STATUSES = frozenset({"no_superior_opportunity"})
''',
)
replace_once(
    "cio_pending_transactions.py",
    '''    launch_at = paper_trading_start_at()
    transactions = _transactions(construction)
''',
    '''    launch_at = paper_trading_start_at()
    briefing_status = (
        str(briefing.get("status", "")).strip().lower()
        if isinstance(briefing, Mapping)
        else ""
    )
    governed_no_action = _governed_no_action_briefing(briefing)
    comparative_no_action = bool(
        governed_no_action
        and briefing_status in _COMPARATIVE_NO_ACTION_STATUSES
    )
    transactions = _transactions(construction)
''',
)
replace_once(
    "cio_pending_transactions.py",
    '''        "report_state": report_state,
        "summary": summary,
''',
    '''        "report_state": report_state,
        "cio_briefing_status": briefing_status or None,
        "safe_abstention_recorded": governed_no_action,
        "comparative_cio_decision_complete": comparative_no_action,
        "summary": summary,
''',
)

replace_once(
    "production_smoke_test.py",
    '''        and int(alpaca.get("quote_count", 0) or 0) > 0
        and isinstance(fred, Mapping)
        and fred.get("status") == "connected"
        and public_state
        and public_state.get("state") in _VALID_PUBLIC_STATES
''',
    '''        and int(alpaca.get("quote_count", 0) or 0) > 0
        and int(alpaca.get("quote_count", 0) or 0)
        == int(alpaca.get("expected_quote_count", 0) or 0)
        and isinstance(fred, Mapping)
        and fred.get("status") == "connected"
        and public_state
        and public_state.get("state") in _VALID_PUBLIC_STATES
        and public_state.get("required_sources_ready") is True
''',
)
replace_once(
    "production_smoke_test.py",
    '''        and cio_report.get("report_state") == "no_transaction_recommended"
        and int(cio_report.get("transaction_count", 0) or 0) == 0
''',
    '''        and cio_report.get("report_state") == "no_transaction_recommended"
        and cio_report.get("comparative_cio_decision_complete") is True
        and int(cio_report.get("transaction_count", 0) or 0) == 0
''',
)

replace_once(
    "production_smoke_test_ui.py",
    '    "governed_paper_outcome_recorded": "Governed paper outcome is recorded",\n',
    '    "governed_paper_outcome_recorded": "Comparative CIO outcome or completed paper execution is recorded",\n',
)
replace_once(
    "production_smoke_test_ui.py",
    '        st.success("All five production runtime checks passed.")\n',
    '        st.success("All five production runtime and decision-readiness checks passed.")\n',
)

replace_once(
    "GOVERNING_SPECIFICATION.md",
    '''The Investment Committee contains six participants:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five perform independent analysis. The Chief Investment Officer chairs the process and issues the final decision. There is no separate investor-goals member. The platform applies one investment objective across all portfolios.
''',
    '''The Investment Committee contains seven participants:

1. Macro & Economic Strategist
2. Market Strategist
3. Cross-Asset Forecast & Scenario Specialist
4. Fundamental & Valuation Analyst
5. Portfolio & Risk Manager
6. Evidence & Governance Officer
7. Chief Investment Officer

The first six perform independent analysis. The Chief Investment Officer chairs the process and issues the final decision. There is no separate investor-goals member. The platform applies one investment objective across all portfolios.
''',
)
replace_once(
    "GOVERNING_SPECIFICATION.md",
    '''Primary question: **What are price, positioning, participation, and liquidity communicating?**

## Fundamental & Valuation Analyst
''',
    '''Primary question: **What are price, positioning, participation, and liquidity communicating?**

## Cross-Asset Forecast & Scenario Specialist

Mission: determine how independently governed forecasts and cross-asset scenarios change the candidate's return distribution, path risk, and timing.

Evaluate forecast horizon, scenario probabilities, model agreement, historical calibration, forecast stability, cross-asset confirmation, path drawdown, contradictory signals, and conditions that would invalidate the forecast translation. Historical evidence remains subordinate to current point-in-time evidence and may only make live conclusions more conservative.

Primary question: **How do calibrated cross-asset scenarios change the candidate's expected return, downside path, and probability of outperforming the best alternative?**

## Fundamental & Valuation Analyst
''',
)

Path("docs/PAPER_TRADING_READINESS.md").write_text(
    '''# Paper Trading Readiness

## Current classification

Capital Intelligence is operationally ready for persistent, authenticated, fail-closed paper observation. It is not yet decision-complete for unattended autonomous portfolio allocation.

The runtime may collect evidence, run the scheduler, preserve state, record safe abstentions, and maintain encrypted backups. A runtime smoke-test pass must not be interpreted as proof that the system evaluated a complete comparative opportunity set.

## Required decision gates

A full paper-CIO decision is complete only when the production cycle has certified candidate evidence for every qualified candidate, compared those candidates with cash and current holdings, completed all six independent specialist analyses, issued a CIO decision, and either produced an executable construction or an evidence-supported no-superior-opportunity conclusion.

`INSUFFICIENT_EVIDENCE` and `IMPLEMENTATION_BLOCKED` are safe governed outcomes, but they are not evidence that the CIO completed a comparative investment decision.

The active free-data publisher currently excludes instruments that lack certified candidate packets. That is safe, but it means the system must report insufficient evidence rather than claim that no superior opportunity exists.

Before the first autonomous position is opened, a recurring publisher must also certify holding evidence for every resulting position. The production context already requires exact holding coverage and will fail closed when that evidence is absent.

## Pilot policy authority

The scheduled CIO construction and paper executor use the same pilot limits:

- minimum cash weight from the versioned free-paper universe;
- maximum batch turnover from that universe;
- the lower of the canonical and pilot single-position limits;
- instrument-specific limits remain enforced by the final execution validator.

## Ten-year historical learning

The ten-year replay is appropriate only as subordinate calibration and governance evidence. It may reduce confidence or position size, but it cannot create a candidate, increase expected return, increase confidence, enlarge a position, authorize execution, or promote policy.

Live calibration requires point-in-time macro coverage, original-decision-horizon outcome alignment, and completed certification. Capability-policy-only outcomes and macro-incomplete cutoffs remain available for audit but are excluded from live forecast, confidence, and sizing calibration.

Ten years do not cover every market regime, security-master change, instrument history, or structural break. Historical learning therefore remains a conservative modifier rather than a primary signal or performance promise.

## Readiness decision

The product is ready for controlled runtime and paper-governance testing. It becomes ready for meaningful unattended paper trading only after real candidate evidence generation and recurring holding-evidence publication are deployed and the stricter production smoke test passes on that release.
''',
    encoding="utf-8",
)

Path("tests/test_complete_paper_readiness_review.py").write_text(
    '''from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cio_pending_transactions import build_pending_transaction_report
from opportunity import OpportunityQueue
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
)
from reporting.daily_cio import DailyCIOBriefingBuilder, DailyCIOStatus
from run_scheduler import _paper_pilot_construction_policy


NOW = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)


def test_empty_review_queue_reports_insufficient_evidence() -> None:
    briefing = DailyCIOBriefingBuilder().build(
        as_of=NOW,
        queue=OpportunityQueue(
            context_identifier="opportunity:test",
            policy_version="opportunity-test.v1",
            ranked=(),
            rejected=(),
        ),
        decisions=(),
        construction=None,
        theses=(),
    )

    assert briefing.status is DailyCIOStatus.INSUFFICIENT_EVIDENCE
    assert "comparative opportunity set is incomplete" in briefing.material_developments
    assert briefing.portfolio_decision == "No portfolio action is permitted."


def test_safe_abstention_is_not_a_completed_comparative_decision() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing={
            "identifier": "daily-cio:test",
            "as_of": NOW.isoformat(),
            "status": "insufficient_evidence",
            "portfolio_decision": "No portfolio action is permitted.",
            "decision_identifier": None,
        },
        generated_at=NOW,
        execution_state="idle",
    )

    assert report["report_state"] == "no_transaction_recommended"
    assert report["safe_abstention_recorded"] is True
    assert report["comparative_cio_decision_complete"] is False


def test_no_superior_opportunity_is_a_completed_comparative_decision() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing={
            "identifier": "daily-cio:test",
            "as_of": NOW.isoformat(),
            "status": "no_superior_opportunity",
            "portfolio_decision": "No portfolio action is required.",
            "decision_identifier": None,
        },
        generated_at=NOW,
        execution_state="idle",
    )

    assert report["comparative_cio_decision_complete"] is True


def test_scheduler_construction_policy_matches_paper_pilot() -> None:
    universe = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
    policy = _paper_pilot_construction_policy()

    assert policy.minimum_cash_weight == universe.minimum_cash_weight
    assert policy.maximum_turnover == universe.maximum_batch_turnover
    assert policy.maximum_position_weight <= universe.maximum_single_instrument_weight
    assert universe.identifier in policy.version


def test_zero_supported_weight_does_not_fall_back_to_assessment_cap() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")

    assert "supported_weight or assessment_cap" not in source
    assert "self.robust_assessor.policy.minimum_reference_weight" in source


def test_smoke_test_requires_complete_provider_and_comparative_outcome() -> None:
    source = Path("production_smoke_test.py").read_text(encoding="utf-8")

    assert 'alpaca.get("expected_quote_count"' in source
    assert 'public_state.get("required_sources_ready") is True' in source
    assert 'cio_report.get("comparative_cio_decision_complete") is True' in source
''',
    encoding="utf-8",
)
