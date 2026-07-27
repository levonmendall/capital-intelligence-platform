"""Security contract tests for authentication, users, and mandate authorization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore

from api import ApiSettings, create_app
from security import (
    AuthenticationService,
    InvalidCredentialsError,
    MandatePermission,
    SQLiteIdentityStore,
    UserRole,
    hash_password,
    verify_password,
)
from tests.test_api import _create_portfolio_database, _create_snapshot_database


ADMIN_PASSWORD = "Admin-Password-42!"
INVESTOR_PASSWORD = "Investor-Password-42!"


def _secured_client(tmp_path: Path):
    snapshot_database = tmp_path / "daily.db"
    portfolio_database = tmp_path / "portfolio.db"
    identity_database = tmp_path / "identity.db"
    _create_snapshot_database(snapshot_database)
    _create_portfolio_database(portfolio_database)
    SQLiteCanonicalPortfolioStore(portfolio_database).append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:INCOME:2026-01-28",
            portfolio_code="INCOME",
            display_name="Income Portfolio",
            constraint_profile="conservative",
            as_of=datetime(2026, 1, 28, 12, tzinfo=timezone.utc),
            starting_capital=80000,
            cash_amount=82000,
            positions=(),
            source_identifiers=("test-fixture",),
        )
    )
    store = SQLiteIdentityStore(identity_database)
    admin = store.create_user(
        email="admin@example.com",
        display_name="Administrator",
        password=ADMIN_PASSWORD,
        roles=(UserRole.ADMINISTRATOR,),
    )
    investor_a = store.create_user(
        email="investor-a@example.com",
        display_name="Investor A",
        password=INVESTOR_PASSWORD,
        investor_identifier="investor-a",
        roles=(UserRole.INVESTOR,),
    )
    store.assign_mandate(investor_a.user_id, "GROWTH", MandatePermission.VIEW)
    investor_b = store.create_user(
        email="investor-b@example.com",
        display_name="Investor B",
        password=INVESTOR_PASSWORD,
        investor_identifier="investor-b",
        roles=(UserRole.INVESTOR,),
    )
    store.assign_mandate(investor_b.user_id, "INCOME", MandatePermission.VIEW)
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=portfolio_database,
        investor_memory_database=tmp_path / "memory.db",
        identity_database=identity_database,
        journal_database=tmp_path / "journal.db",
        replay_directory=None,
        authentication_required=True,
    )
    authentication = AuthenticationService(store, required=True)
    client = TestClient(
        create_app(settings=settings, authentication=authentication)
    )
    return client, store, admin, investor_a, investor_b


def _login(client: TestClient, email: str, password: str) -> dict:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_password_hashes_use_scrypt_and_never_store_plaintext() -> None:
    encoded = hash_password(INVESTOR_PASSWORD, salt=b"test-auth-salt-1")

    assert INVESTOR_PASSWORD not in encoded
    assert encoded.startswith("scrypt-v1$")
    assert verify_password(INVESTOR_PASSWORD, encoded)
    assert not verify_password("Wrong-Password-42!", encoded)
    with pytest.raises(ValueError):
        hash_password("too-short")


def test_health_is_public_but_intelligence_requires_authentication(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    response = client.get("/v1/daily/latest")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_and_current_user_return_only_safe_identity_fields(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)

    assert client.post(
        "/v1/auth/login",
        json={"email": "investor-a@example.com", "password": "wrong"},
    ).status_code == 401
    tokens = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)
    current = client.get("/v1/auth/me", headers=_headers(tokens))

    assert current.status_code == 200
    payload = current.json()
    assert payload["email"] == "investor-a@example.com"
    assert payload["investor_identifier"] == "investor-a"
    assert payload["roles"] == ["investor"]
    assert payload["mandates"] == [
        {"mandate_code": "GROWTH", "permission": "view"}
    ]
    assert "password" not in str(payload).lower()


def test_refresh_rotates_both_credentials_and_revokes_old_session(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    first = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)

    refreshed = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert refreshed.status_code == 200
    second = refreshed.json()
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]
    assert client.get(
        "/v1/auth/me", headers=_headers(first)
    ).status_code == 401
    assert client.post(
        "/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    ).status_code == 401
    assert client.get(
        "/v1/auth/me", headers=_headers(second)
    ).status_code == 200


def test_logout_revokes_the_access_token(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)

    assert client.post(
        "/v1/auth/logout", headers=_headers(tokens)
    ).status_code == 204
    assert client.get(
        "/v1/auth/me", headers=_headers(tokens)
    ).status_code == 401


def test_portfolio_list_and_detail_are_mandate_scoped(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    investor_a = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)
    investor_b = _login(client, "investor-b@example.com", INVESTOR_PASSWORD)

    growth = client.get("/v1/portfolios", headers=_headers(investor_a))
    income = client.get("/v1/portfolios", headers=_headers(investor_b))
    assert [item["code"] for item in growth.json()["items"]] == ["GROWTH"]
    assert [item["code"] for item in income.json()["items"]] == ["INCOME"]
    assert client.get(
        "/v1/portfolios/INCOME", headers=_headers(investor_a)
    ).status_code == 404
    assert client.get(
        "/v1/portfolios/GROWTH", headers=_headers(investor_a)
    ).status_code == 200


def test_retired_investor_memory_routes_cannot_be_reactivated_by_identity(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    investor_a = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)

    own = client.get(
        "/v1/investor-memory/investor-a",
        headers=_headers(investor_a),
    )
    other = client.get(
        "/v1/investor-memory/investor-b",
        headers=_headers(investor_a),
    )
    assert own.status_code == 404
    assert other.status_code == 404


def test_administrator_can_create_users_and_assign_access(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    admin_tokens = _login(client, "admin@example.com", ADMIN_PASSWORD)

    created = client.post(
        "/v1/users",
        headers=_headers(admin_tokens),
        json={
            "email": "advisor@example.com",
            "display_name": "Advisor",
            "password": "Advisor-Password-42!",
            "roles": ["advisor"],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["user_id"]
    granted_mandate = client.post(
        f"/v1/users/{user_id}/mandates",
        headers=_headers(admin_tokens),
        json={"mandate_code": "GROWTH", "permission": "manage"},
    )
    granted_investor = client.post(
        f"/v1/users/{user_id}/investor-access",
        headers=_headers(admin_tokens),
        json={"investor_identifier": "investor-a", "permission": "reflect"},
    )
    assert granted_mandate.status_code == 200
    assert granted_investor.status_code == 200

    advisor = _login(client, "advisor@example.com", "Advisor-Password-42!")
    assert client.get(
        "/v1/portfolios/GROWTH", headers=_headers(advisor)
    ).status_code == 200
    assert client.get(
        "/v1/investor-memory/investor-a", headers=_headers(advisor)
    ).status_code == 404
    assert client.get("/v1/users", headers=_headers(advisor)).status_code == 403


def test_disabling_user_revokes_active_sessions(tmp_path) -> None:
    client, _, _, investor_a, _ = _secured_client(tmp_path)
    admin = _login(client, "admin@example.com", ADMIN_PASSWORD)
    investor = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)

    disabled = client.post(
        f"/v1/users/{investor_a.user_id}/disable",
        headers=_headers(admin),
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert client.get(
        "/v1/auth/me", headers=_headers(investor)
    ).status_code == 401
    assert client.post(
        "/v1/auth/login",
        json={
            "email": "investor-a@example.com",
            "password": INVESTOR_PASSWORD,
        },
    ).status_code == 401


def test_authentication_audit_history_is_append_only(tmp_path) -> None:
    _, store, _, _, _ = _secured_client(tmp_path)
    with pytest.raises(InvalidCredentialsError):
        store.login(email="investor-a@example.com", password="wrong")
    events = store.audit_events()
    assert any(
        event["event_type"] == "login" and not bool(event["success"])
        for event in events
    )

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE auth_audit_events SET detail = 'changed'"
            )


def test_environment_loaded_settings_require_authentication_by_default() -> None:
    runtime = ApiSettings.from_env({})
    explicit_fixture = ApiSettings()

    assert runtime.authentication_required is True
    assert explicit_fixture.authentication_required is False
