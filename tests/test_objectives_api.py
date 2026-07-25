"""API contract tests for investor objectives and Personal CIO briefs."""

from tests.test_authentication_authorization import (
    INVESTOR_PASSWORD,
    _headers,
    _login,
    _secured_client,
)


def test_missing_objectives_are_disclosed_without_assumptions(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )

    response = client.get(
        "/v1/personal-cio/investor-a/latest",
        headers=_headers(tokens),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["action_status"] == "monitor"
    assert payload["portfolio_alignment"]["score"] is None
    assert payload["portfolio_alignment"][
        "is_goal_success_probability"
    ] is False


def test_investor_can_record_policy_goal_and_receive_brief(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )
    headers = _headers(tokens)

    policy = client.post(
        "/v1/investment-policy/investor-a",
        headers=headers,
        json={
            "primary_objective": "long_term_growth",
            "time_horizon_years": 15,
            "risk_capacity": "high",
            "risk_preference": "moderate",
            "required_return": 0.06,
            "maximum_tolerable_drawdown": 0.2,
            "minimum_liquidity_months": 12,
        },
    )
    goal = client.post(
        "/v1/goals/investor-a",
        headers=headers,
        json={
            "goal_key": "retirement",
            "name": "Retirement",
            "goal_type": "retirement",
            "priority": "essential",
            "target_date": "2041-07-25",
            "target_amount": 1_000_000,
            "funded_amount": 300_000,
            "portfolio_codes": ["GROWTH"],
            "liquidity_required": False,
        },
    )
    brief = client.get(
        "/v1/personal-cio/investor-a/latest",
        headers=headers,
    )

    assert policy.status_code == 200, policy.text
    assert goal.status_code == 200, goal.text
    assert brief.status_code == 200, brief.text
    payload = brief.json()
    assert payload["what_changed"]
    assert payload["why_it_matters"]
    assert payload["portfolio_effect"]
    assert payload["recommended_action"]
    assert payload["policy_identifier"] == policy.json()["identifier"]
    assert payload["portfolio_alignment"]["score"] is not None


def test_objectives_cannot_cross_investor_boundaries(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )
    headers = _headers(tokens)

    assert client.get(
        "/v1/investment-policy/investor-b",
        headers=headers,
    ).status_code == 404
    assert client.post(
        "/v1/investment-policy/investor-b",
        headers=headers,
        json={
            "primary_objective": "growth",
            "time_horizon_years": 10,
            "risk_capacity": "high",
            "risk_preference": "moderate",
        },
    ).status_code == 404
    assert client.get(
        "/v1/personal-cio/investor-b/latest",
        headers=headers,
    ).status_code == 404


def test_policy_updates_append_history_instead_of_rewriting(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )
    headers = _headers(tokens)
    base = {
        "primary_objective": "long_term_growth",
        "time_horizon_years": 15,
        "risk_capacity": "high",
        "risk_preference": "moderate",
    }

    first = client.post(
        "/v1/investment-policy/investor-a",
        headers=headers,
        json=base,
    )
    second = client.post(
        "/v1/investment-policy/investor-a",
        headers=headers,
        json={**base, "time_horizon_years": 12},
    )
    history = client.get(
        "/v1/investment-policy/investor-a/history",
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert history.status_code == 200
    assert history.json()["total"] == 2
    assert second.json()["supersedes_identifier"] == first.json()["identifier"]
