from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "production_context_publication_governed.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_publisher() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from opportunity import AlternativeKind, AlternativeUse, OpportunityEngine, OpportunitySetContext\n",
        "from opportunity import AlternativeKind, AlternativeUse, OpportunityEngine, OpportunitySetContext\n"
        "from opportunity.competitive import prepare_competitive_opportunity_set\n",
        label="competitive opportunity import",
    )
    old = '''    alternatives.extend(
        AlternativeUse(
            identifier=candidate.identifier,
            kind=AlternativeKind.QUALIFIED_CANDIDATE,
            expected_return=candidate.probability_weighted_expected_return,
            implementation_cost_return=candidate.implementation_cost_return,
            evidence_quality=candidate.evidence_quality.score,
            liquidity_score=candidate.liquidity_score,
            current_weight=0.0,
        )
        for candidate in build_result.candidates
    )
    opportunity_context = OpportunitySetContext(
        identifier=opportunity_identifier,
        as_of=decision_as_of,
        alternatives=tuple(alternatives),
    )
    capability_authority = BoundedPilotCapabilityAuthority.from_universe(base_universe)
    queue = OpportunityEngine(
        universe_policy=RecommendationUniversePolicy(
            asset_class_authority=capability_authority,
        )
    ).build_queue(
        build_result.candidates,
        opportunity_context,
    )
'''
    new = '''    baseline_opportunity_context = OpportunitySetContext(
        identifier=opportunity_identifier,
        as_of=decision_as_of,
        alternatives=tuple(alternatives),
    )
    capability_authority = BoundedPilotCapabilityAuthority.from_universe(base_universe)
    opportunity_engine = OpportunityEngine(
        universe_policy=RecommendationUniversePolicy(
            asset_class_authority=capability_authority,
        )
    )
    competitive = prepare_competitive_opportunity_set(
        opportunity_engine,
        build_result.candidates,
        baseline_opportunity_context,
    )
    # Candidate evidence is immutable; only its point-in-time opportunity-cost field
    # is reconciled to the same current cash/holding baseline consumed by qualification.
    build_result = replace(build_result, candidates=competitive.candidates)
    opportunity_context = competitive.context
    queue = competitive.queue
'''
    text = replace_once(
        text,
        old,
        new,
        label="two-pass opportunity construction",
    )
    text = replace_once(
        text,
        '        "capability_policy": capability_authority.coverage_payload(),\n',
        '        "capability_policy": capability_authority.coverage_payload(),\n'
        '        "baseline_opportunity_cost": competitive.baseline_opportunity_cost,\n'
        '        "qualified_candidate_alternative_count": len(\n'
        '            competitive.candidate_alternative_identifiers\n'
        '        ),\n',
        label="competition diagnostics",
    )
    PUBLISHER.write_text(text, encoding="utf-8")


def main() -> None:
    patch_publisher()
    subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "tests/test_competitive_opportunity_context.py",
            "tests/test_production_invested_candidate_reachability.py",
            "tests/test_production_governed_candidate_reachability.py",
            "tests/test_production_context_publication_runtime.py",
            "tests/test_opportunity_engine.py",
            "tests/test_persistent_cash_diagnostic.py",
            "tests/test_committee_cio_information_trace.py",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
