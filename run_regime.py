"""Run the canonical point-in-time economic-regime pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from intelligence.regime_pipeline import (
    InstitutionalRegimeRun,
    SeriesLoadState,
    build_fred_regime_pipeline,
)


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
    arguments = parser.parse_args()
    as_of = _parse_as_of(arguments.as_of)
    run = build_fred_regime_pipeline().run(as_of=as_of)
    print(format_run(run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
