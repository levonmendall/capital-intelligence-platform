from __future__ import annotations

from types import SimpleNamespace

from application.global_rotation_preview import build_global_rotation_preview
from portfolio.global_rotation import (
    CashCompetitionState,
    GlobalOpportunityDomain,
    GlobalOpportunitySignal,
    GlobalRotationContext,
)


def _candidate(identifier: str, symbol: str, maximum: float = 0.10):
    return SimpleNamespace(
        identifier=identifier,
        instrument=SimpleNamespace(
            symbol=symbol,
            instrument_id=f"instrument:{symbol}",
            average_daily_dollar_volume=100_000_000.0,
            uses_derivatives=False,
        ),
        net_expected_return=0.08,
        opportunity_cost_return=0.03,
        decision_horizon_days=90,
        maximum_position_weight=maximum,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
    )


def _signal(identifier: str, rank: int, score: float):
    return GlobalOpportunitySignal(
        candidate_identifier=identifier,
        domain=GlobalOpportunityDomain.EQUITY,
        rank=rank,
        score=score,
        leadership_state="leading",
        leadership_score=score,
        mispriced_change_state="constructive_mispriced_change",
        mispriced_change_score=0.5,
        forward_impulse=0.03,
        expected_return_edge=0.04,
        evidence_score=0.9,
        evidence_identifiers=(f"evidence:{identifier}",),
    )


def test_global_preview_requests_larger_targets_for_stronger_opportunities():
    strong = _candidate("candidate:strong", "AAA")
    developing = _candidate("candidate:developing", "BBB")
    context = GlobalRotationContext(
        as_of=None,
        signals=(
            _signal(strong.identifier, 1, 0.82),
            _signal(developing.identifier, 2, 0.60),
        ),
        cash_expected_return=0.03,
        minimum_cash_weight=0.05,
        current_cash_weight=1.0,
        excess_cash_weight=0.95,
        cash_competition_state=CashCompetitionState.DEPLOYMENT_OPPORTUNITY,
    )

    class Portfolio:
        cash_weight = 1.0

        def current_weight(self, _symbol):
            return 0.0

        def profile(self, _identifier):
            return SimpleNamespace(
                sector="test",
                factor_loadings=(),
                correlation_bucket="test",
                derivative_lifecycle=None,
            )

        def request(self, *, identifier, intents):
            return SimpleNamespace(identifier=identifier, intents=intents)

    class Engine:
        policy = SimpleNamespace(version="construction.test")

        def __init__(self):
            self.intents = ()

        def construct(self, request):
            self.intents = request.intents
            return SimpleNamespace(
                request_identifier=request.identifier,
                status=SimpleNamespace(value="accepted"),
                policy_version="construction.test",
                target_weights=(("AAA", 0.08), ("BBB", 0.03)),
                target_cash_weight=0.89,
                expected_return_improvement=0.01,
                blocks=(),
            )

    engine = Engine()
    preview = build_global_rotation_preview(
        cycle_identifier="cycle:test",
        candidates=(strong, developing),
        portfolio=Portfolio(),
        construction_engine=engine,
        rotation_context=context,
    )
    requested = dict(preview.requested_targets)
    assert requested[strong.identifier] == 0.10
    assert requested[developing.identifier] == 0.03
    assert engine.intents[0].priority_rank == 1
    assert engine.intents[1].priority_rank == 2


def test_zero_global_score_does_not_create_a_preview_buy():
    weak = _candidate("candidate:weak", "CCC")
    context = GlobalRotationContext(
        as_of=None,
        signals=(_signal(weak.identifier, 1, 0.20),),
        cash_expected_return=0.03,
        minimum_cash_weight=0.05,
        current_cash_weight=1.0,
        excess_cash_weight=0.95,
        cash_competition_state=CashCompetitionState.CASH_LEADING_ESTIMATE,
    )

    class Portfolio:
        cash_weight = 1.0
        def current_weight(self, _symbol): return 0.0
        def profile(self, _identifier): raise AssertionError("no intent should require a profile")

    class Engine:
        policy = SimpleNamespace(version="construction.test")
        def construct(self, _request): raise AssertionError("construction should not run")

    preview = build_global_rotation_preview(
        cycle_identifier="cycle:weak",
        candidates=(weak,),
        portfolio=Portfolio(),
        construction_engine=Engine(),
        rotation_context=context,
    )
    assert preview.status == "no_action"
    assert preview.requested_for(weak.identifier) == 0.0
