"""Architecture tests proving personal goals are outside the active API."""

from tests.test_authentication_authorization import (
    INVESTOR_PASSWORD,
    _headers,
    _login,
    _secured_client,
)


DEPRECATED_PATHS = (
    "/v1/investment-policy/investor-a",
    "/v1/investment-policy/investor-a/history",
    "/v1/goals/investor-a",
    "/v1/personal-cio/investor-a/latest",
    "/v1/personal-cio/investor-a/history",
)


def test_goal_based_routes_are_not_registered(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )
    headers = _headers(tokens)

    for path in DEPRECATED_PATHS:
        assert client.get(path, headers=headers).status_code == 404
        assert client.post(path, headers=headers, json={}).status_code == 404


def test_openapi_excludes_goal_and_personal_cio_contracts(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    paths = set(payload["paths"])
    assert not any("investment-policy" in path for path in paths)
    assert not any("/goals/" in path for path in paths)
    assert not any("personal-cio" in path for path in paths)


def test_core_cio_api_remains_available_without_objectives(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )
    headers = _headers(tokens)

    daily = client.get("/v1/daily/latest", headers=headers)
    environment = client.get("/v1/environment/latest", headers=headers)
    portfolios = client.get("/v1/portfolios", headers=headers)

    assert daily.status_code == 200, daily.text
    assert environment.status_code == 200, environment.text
    assert portfolios.status_code == 200, portfolios.text


def test_investor_boundary_still_protects_portfolios(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(
        client,
        "investor-a@example.com",
        INVESTOR_PASSWORD,
    )
    headers = _headers(tokens)

    assert client.get("/v1/portfolios/COMPOUNDING", headers=headers).status_code == 200
    assert client.get("/v1/portfolios/INCOME", headers=headers).status_code == 404