from __future__ import annotations

from types import SimpleNamespace

from cio_investment_memo import build_investment_memo, render_investment_memo


def _bundle() -> dict[str, object]:
    return {
        "decision_identifier": "decision:klac",
        "cycle_identifier": "cycle:current",
        "snapshot_identifier": "snapshot:klac",
        "decision_actions": {
            "selected_action": "reduce",
            "effective_action": "hold",
            "deferred": True,
        },
        "auditability": {"status": "auditable", "issues": []},
        "release_identity": {"decision_code_version": "release-abc"},
        "component_status": {
            "decision_evaluation": {"status": "pending_horizon"}
        },
        "records": {
            "cio_decision": {
                "identifier": "decision:klac",
                "candidate_identifier": "candidate:klac:now",
                "best_alternative_identifier": "holding:MCD",
                "action": "hold",
                "deferred_action": "reduce",
                "hysteresis_applied": True,
                "expected_return": 0.3867,
                "effective_opportunity_cost": 0.3699,
                "final_confidence": 0.5622,
                "decision_horizon_days": 365,
                "rationale": (
                    "The holding remains positive in isolation, but a feasible "
                    "alternative is materially superior after costs. robust edge is "
                    "-3.51% and stressed edge is -6.18%."
                ),
                "portfolio_impact": "Hold without a weight change.",
                "catalysts": [
                    "Company quality and momentum improved",
                    "quality score=1.000",
                ],
                "contradictory_evidence": [
                    "analytical coverage is incomplete",
                    "Maximum historical drawdown=-43.53%",
                ],
                "key_assumptions": [
                    "Normalized financials remain representative",
                ],
                "invalidation_conditions": [
                    "A qualified replacement offers a materially superior edge",
                ],
                "dissent": {
                    "opposing_conclusion": (
                        "The downside scenario implies a material path drawdown."
                    )
                },
                "return_reconciliation": {
                    "expected_downside": -0.3473,
                    "probability_of_success": 0.7522,
                },
            },
            "daily_cio_briefing": {
                "portfolio_decision": (
                    "CIO decision: hold while the reduction remains in cooldown."
                ),
                "what_changed": "Company evidence changed the expected return.",
            },
            "decision_evidence_snapshot": {
                "current_portfolio_weight": 0.0008,
                "funding_source": "cash above minimum reserve",
            },
            "portfolio_construction": {
                "target_weights": [{"symbol": "KLAC", "weight": 0.0008}],
                "trades": [],
            },
            "decision_evaluation": None,
        },
    }


def test_memo_explains_selected_and_effective_action() -> None:
    memo = build_investment_memo(
        _bundle(),
        market_backdrop="Constructive growth with contained volatility.",
        portfolio_posture="1% invested",
    )

    assert memo["symbol"] == "KLAC"
    assert memo["selected_action"] == "Reduce"
    assert memo["effective_action"] == "Hold"
    assert memo["deferred"] is True
    assert "robust edge -3.5%" in memo["rationale"]
    assert "stressed edge -6.2%" in memo["rationale"]
    assert "persistence or cooldown" in memo["rationale"]
    assert memo["investment_question"].startswith("Does KLAC deserve capital")
    assert memo["strongest_dissent"].startswith("The downside scenario")
    assert "Quality evidence scored 100%." in memo["bull_case"]
    assert memo["audit"]["auditability"] == "Auditable"
    assert memo["audit"]["evaluation_status"] == "Pending Horizon"


def test_missing_content_is_disclosed_not_invented() -> None:
    memo = build_investment_memo(
        {
            "records": {},
            "decision_actions": {},
            "auditability": {"status": "non_auditable"},
        }
    )

    assert memo["symbol"] == "Current opportunity"
    assert memo["rationale"] == "Not separately recorded for this decision."
    assert memo["bull_case"] == ()
    assert memo["bear_case"] == ()
    assert memo["implementation"] == "No exact-lineage paper transaction is proposed."


def test_renderer_includes_investment_memo_sections() -> None:
    calls: list[str] = []
    streamlit = SimpleNamespace(
        markdown=lambda content, **kwargs: calls.append(str(content))
    )

    memo = render_investment_memo(
        streamlit,
        _bundle(),
        market_backdrop="Constructive growth with contained volatility.",
        portfolio_posture="1% invested",
    )

    markup = "\n".join(calls)
    assert memo["symbol"] == "KLAC"
    assert "CIO investment memo" in markup
    assert "The investment question" in markup
    assert "Why the CIO reached this conclusion" in markup
    assert "Bull case" in markup
    assert "Bear case" in markup
    assert "Portfolio impact" in markup
    assert "What would change the decision" in markup
    assert "Selected: Reduce" in markup
    assert "Effective now: Hold" in markup
    assert "real-money" not in markup.lower()
