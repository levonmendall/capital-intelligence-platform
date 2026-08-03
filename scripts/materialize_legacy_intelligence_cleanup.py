"""Remove the disconnected legacy intelligence decision stack.

The active `intelligence.recommendation` evidence contract is intentionally preserved.
The removed modules have no supported production inbound edge and are retained in Git
history rather than copied into an executable archive package.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REMOVE_FILES = (
    "intelligence/cio.py",
    "intelligence/decision_discipline.py",
    "intelligence/forecast.py",
    "intelligence/forecast_engine.py",
    "intelligence/forecast_strategy.py",
    "intelligence/observation.py",
    "intelligence/observation_adapter.py",
    "intelligence/portfolio_manager.py",
    "intelligence/rebalancer.py",
    "intelligence/recommendation_builder.py",
    "intelligence/recommendation_engine.py",
    "intelligence/recommendation_rules.py",
    "intelligence/state.py",
    "intelligence/state_engine.py",
    "intelligence/strategies/__init__.py",
    "intelligence/strategies/rule_based.py",
    "intelligence/theme.py",
    "intelligence/theme_engine.py",
    "intelligence/thesis.py",
    "intelligence/thesis_engine.py",
    "tests/test_decision_discipline.py",
    "tests/test_point_in_time_observation.py",
    "tests/test_portfolio_manager.py",
    "tests/test_rebalancer.py",
    "tests/test_recommendation_engine.py",
    "tests/test_recommendation_rules.py",
    "tests/test_state_engine.py",
    "tests/test_theme_engine.py",
    "tests/test_thesis_engine.py",
)

EXPORT_BLOCKS = (
    '''    "ChiefInvestmentOfficer": (
        "intelligence.cio",
        "ChiefInvestmentOfficer",
    ),
''',
    '''    "GuidanceSynthesizer": (
        "intelligence.cio",
        "GuidanceSynthesizer",
    ),
''',
)


def main() -> None:
    for relative in REMOVE_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"missing expected removal target: {relative}")
        path.unlink()

    init_path = ROOT / "intelligence/__init__.py"
    text = init_path.read_text(encoding="utf-8")
    for block in EXPORT_BLOCKS:
        if text.count(block) != 1:
            raise RuntimeError("legacy intelligence export block changed")
        text = text.replace(block, "")
    init_path.write_text(text, encoding="utf-8")

    manifest = ROOT / "archive/REMOVED_LEGACY_INTELLIGENCE_2026-08-03.md"
    if manifest.exists():
        raise RuntimeError("legacy intelligence removal manifest already exists")
    manifest.write_text(
        """# Removed legacy intelligence stack — 2026-08-03

The following disconnected pre-canonical investment architecture was removed after a
repository-wide import and runtime-entrypoint audit:

- the parallel `intelligence.cio` guidance synthesizer;
- legacy recommendation builder, rules, and recommendation engine;
- forecast, strategy, state, theme, and thesis engines and contracts;
- legacy portfolio-manager and rebalancer contracts;
- old point-in-time observation adapters and decision-discipline helper;
- dedicated tests that exercised only those retired contracts.

The active `intelligence.recommendation` evidence model remains because current
committee, portfolio-fit, monitoring, and reporting paths still use it. The current
`cio` package remains the sole canonical CIO decision authority.

Git history is the source archive. No executable copy is kept under `archive/`.

This cleanup does not alter thresholds, market scope, specialist count, CIO authority,
construction authority, evidence governance, paper execution, or the prohibition on
live money.
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
