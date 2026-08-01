from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests/test_canonical_cio.py"
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    "    EvidenceQuality,\n    IndependentSpecialistPacket,\n",
    "    EvidenceQuality,\n    EvidenceVetoCategory,\n    IndependentSpecialistPacket,\n",
    "evidence veto category import",
)
replace_once(
    "    vetoes: tuple[str, ...] = (),\n    blocks: tuple[str, ...] = (),\n",
    "    vetoes: tuple[str, ...] = (),\n"
    "    veto_categories: tuple[EvidenceVetoCategory, ...] = (),\n"
    "    blocks: tuple[str, ...] = (),\n",
    "analysis veto category argument",
)
replace_once(
    "        veto_reasons=vetoes,\n        implementation_blocks=blocks,\n",
    "        veto_reasons=vetoes,\n"
    "        veto_categories=veto_categories,\n"
    "        implementation_blocks=blocks,\n",
    "analysis veto category handoff",
)
replace_once(
    "    evidence_vetoes: tuple[str, ...] = (),\n    implementation_blocks: tuple[str, ...] = (),\n",
    "    evidence_vetoes: tuple[str, ...] = (),\n"
    "    evidence_veto_categories: tuple[EvidenceVetoCategory, ...] = (),\n"
    "    implementation_blocks: tuple[str, ...] = (),\n",
    "packet veto category argument",
)
replace_once(
    "                vetoes=(\n"
    "                    evidence_vetoes\n"
    "                    if role is SpecialistRole.EVIDENCE_GOVERNANCE\n"
    "                    else ()\n"
    "                ),\n"
    "                blocks=(\n",
    "                vetoes=(\n"
    "                    evidence_vetoes\n"
    "                    if role is SpecialistRole.EVIDENCE_GOVERNANCE\n"
    "                    else ()\n"
    "                ),\n"
    "                veto_categories=(\n"
    "                    evidence_veto_categories\n"
    "                    if role is SpecialistRole.EVIDENCE_GOVERNANCE\n"
    "                    else ()\n"
    "                ),\n"
    "                blocks=(\n",
    "packet veto category handoff",
)
replace_once(
    '''        _packet(
            evidence_vetoes=("filing timestamp cannot be reproduced",),
            weight=0.08,
        ),
''',
    '''        _packet(
            evidence_vetoes=("filing timestamp cannot be reproduced",),
            evidence_veto_categories=(
                EvidenceVetoCategory.INTEGRITY_EMERGENCY,
            ),
            weight=0.08,
        ),
''',
    "integrity emergency classification",
)
old = '''def test_positive_holding_is_reduced_when_a_superior_alternative_exists() -> None:
    candidate = _candidate(
        current_weight=0.08,
        base_return=0.08,
        bull_return=0.14,
        bear_return=0.01,
        opportunity_cost=0.12,
    )
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(weight=0.08),
    )

    assert candidate.net_expected_return > 0.0
    assert decision.action in {CIOAction.REDUCE, CIOAction.EXIT}
'''
new = '''def test_positive_holding_is_reduced_after_superior_alternative_persists() -> None:
    candidate = _candidate(
        current_weight=0.08,
        base_return=0.08,
        bull_return=0.14,
        bear_return=0.01,
        opportunity_cost=0.12,
    )
    universe = RecommendationUniversePolicy().evaluate(candidate.instrument)

    first = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(weight=0.08),
    )

    assert candidate.net_expected_return > 0.0
    assert first.action is CIOAction.HOLD
    assert first.deferred_action in {CIOAction.REDUCE, CIOAction.EXIT}
    prior = PriorDecisionContext(
        candidate_identifier=candidate.identifier,
        prior_decision_identifier=first.identifier,
        prior_action=first.action,
        prior_target_weight=None,
        decided_at=AS_OF - timedelta(days=1),
        thesis_state=ThesisState.ACTIVE,
        consecutive_supportive_cycles=0,
        consecutive_opposing_cycles=1,
    )
    confirmed = ChiefInvestmentOfficer().synthesize(
        candidate,
        universe,
        _packet(weight=0.08),
        prior_context=prior,
    )
    assert confirmed.action in {CIOAction.REDUCE, CIOAction.EXIT}
'''
replace_once(old, new, "superior alternative persistence test")
path.write_text(text, encoding="utf-8")
