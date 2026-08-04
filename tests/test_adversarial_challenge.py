from datetime import datetime, timezone

from cio.adversarial_challenge import (
    AdversarialCIOChallengeEngine,
    DecisionProposal,
    ProposedAction,
)


def test_buy_challenge_is_non_voting_and_uses_supplied_evidence():
    proposal = DecisionProposal(
        identifier="decision-1",
        as_of=datetime(2026, 8, 3, tzinfo=timezone.utc),
        action=ProposedAction.BUY,
        rationale=("Expected return exceeds cash.",),
        supporting_evidence=("Margins and revisions improved.",),
        opposing_evidence=("The valuation discount may reflect permanent impairment.",),
        hidden_assumptions=("Pricing power persists.",),
        cash_case_evidence=("Downside distribution remains wide.",),
        replacement_evidence=("A cheaper peer has similar exposure.",),
        tail_risks=("Refinancing fails during a credit shock.",),
    )
    challenge = AdversarialCIOChallengeEngine().challenge(proposal)
    assert "loses 30%" in challenge.pre_mortem
    assert challenge.strongest_case_against.startswith("The valuation")
    payload = challenge.to_dict()
    assert payload["veto_authority"] is False
    assert payload["trade_authority"] is False
