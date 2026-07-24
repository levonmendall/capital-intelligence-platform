"""Run the canonical point-in-time economic-regime pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from committee import (
    RegimeCommitteeDecision,
    RegimeGovernanceWorkflow,
)
from intelligence.regime_pipeline import (
    InstitutionalRegimeRun,
    SeriesLoadState,
    build_fred_regime_pipeline,
)
from journal import SQLiteAppendOnlyJournal


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "as-of must be an ISO-8601 datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "as-of must include a timezone"
        )
    return parsed


def format_run(run: InstitutionalRegimeRun) -> str:
    """Return a concise human-readable institutional regime result."""

    assessment = run.assessment
    lines = [
        "Capital Intelligence Platform — Institutional Regime",
        "----------------------------------------------------",
        f"Decision time: {run.as_of.isoformat()}",
        f"Provider: {run.provider}",
        f"Regime: {assessment.result.regime.value}",
        (
            "Engine confidence: "
            f"{assessment.result.confidence:.0%}"
        ),
        (
            "Evidence-adjusted confidence: "
            f"{assessment.confidence:.0%}"
        ),
        (
            "Evidence coverage: "
            f"{assessment.evidence.data_coverage:.0%}"
        ),
        (
            "Evidence quality: "
            f"{assessment.evidence.quality_score:.0%}"
        ),
        (
            "Series loaded: "
            f"{run.loaded_count}/{len(run.loads)}"
        ),
    ]
    unavailable = [
        load
        for load in run.loads
        if load.state is SeriesLoadState.UNAVAILABLE
    ]
    if unavailable:
        lines.append("")
        lines.append("Unavailable evidence")
        for load in unavailable:
            lines.append(
                f"- {load.request.signal}: {load.error}"
            )
    return "\n".join(lines)


def format_decision(decision: RegimeCommitteeDecision) -> str:
    """Return a concise governed committee disposition."""

    lines = [
        "Regime Committee Governance",
        "---------------------------",
        f"Decision: {decision.decision_identifier}",
        f"Outcome: {decision.outcome.value}",
        f"Policy: {decision.policy_version}",
        (
            "Recommendation: "
            f"{decision.recommendation.action.value} "
            f"{decision.recommendation.target}"
        ),
        f"Rationale: {decision.rationale}",
    ]
    if decision.committee_result is not None:
        committee_decision = (
            decision.committee_result.decision
        )
        lines.extend(
            (
                (
                    "Committee consensus: "
                    f"{committee_decision.consensus.value}"
                ),
                (
                    "Committee confidence: "
                    f"{committee_decision.confidence:.0%}"
                ),
                (
                    "Specialist opinions: "
                    f"{committee_decision.opinion_count}"
                ),
            )
        )
    if decision.no_action is not None:
        lines.append(
            "Next review: "
            f"{decision.no_action.review_at.isoformat()}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the canonical point-in-time economic-regime "
            "pipeline."
        )
    )
    parser.add_argument(
        "--as-of",
        help=(
            "Timezone-aware ISO-8601 decision timestamp. "
            "Defaults to the current UTC time."
        ),
    )
    parser.add_argument(
        "--journal",
        type=Path,
        help=(
            "Optional SQLite path for appending the complete "
            "regime run to the tamper-evident journal."
        ),
    )
    parser.add_argument(
        "--code-version",
        help=(
            "Optional release or commit identifier recorded with "
            "a journaled run."
        ),
    )
    parser.add_argument(
        "--govern",
        action="store_true",
        help=(
            "Translate the regime assessment into a recommendation "
            "and run committee governance. No trades are executed."
        ),
    )
    arguments = parser.parse_args()
    as_of = _parse_as_of(arguments.as_of)
    run = build_fred_regime_pipeline().run(as_of=as_of)
    print(format_run(run))
    decision = None
    if arguments.govern:
        decision = RegimeGovernanceWorkflow().evaluate(run)
        print("")
        print(format_decision(decision))
    if arguments.journal is not None:
        journal = SQLiteAppendOnlyJournal(arguments.journal)
        event = journal.append_regime_run(
            run,
            code_version=arguments.code_version,
        )
        print("")
        print(
            "Journal event: "
            f"{event.event_identifier} "
            f"(sequence {event.sequence})"
        )
        if decision is not None:
            decision_event = (
                journal.append_regime_committee_decision(
                    decision
                )
            )
            print(
                "Decision journal event: "
                f"{decision_event.event_identifier} "
                f"(sequence {decision_event.sequence})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
