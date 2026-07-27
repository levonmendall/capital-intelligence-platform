"""API contracts for authenticated selective alert preferences and inbox."""

from __future__ import annotations

from datetime import datetime, timezone

from delivery import (
    AlertChannel,
    AlertDeliveryService,
    AlertMessage,
    AlertPriority,
    AlertTopic,
)
from tests.test_authentication_authorization import (
    INVESTOR_PASSWORD,
    _headers,
    _login,
    _secured_client,
)


def test_alert_preferences_require_authentication(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)

    assert client.get("/v1/alerts/preferences").status_code == 401
    tokens = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)
    response = client.get(
        "/v1/alerts/preferences",
        headers=_headers(tokens),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["channels"] == ["in_app"]
    assert "daily_summary" not in payload["topics"]


def test_investor_can_update_selective_alert_preferences(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)

    updated = client.put(
        "/v1/alerts/preferences",
        headers=_headers(tokens),
        json={
            "timezone_name": "America/Los_Angeles",
            "delivery_hour": 6,
            "channels": ["in_app"],
            "topics": ["cio_decision", "implementation", "daily_briefing"],
            "email_address": "investor-a@example.com",
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["timezone_name"] == "America/Los_Angeles"
    assert payload["delivery_hour"] == 6
    assert "minimum_conviction_change" not in payload
    assert "daily_briefing" in payload["topics"]


def test_email_preferences_require_runtime_email_configuration(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    tokens = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)

    response = client.put(
        "/v1/alerts/preferences",
        headers=_headers(tokens),
        json={
            "timezone_name": "UTC",
            "delivery_hour": 8,
            "channels": ["email"],
            "topics": ["cio_decision"],
            "email_address": "investor-a@example.com",
        },
    )

    assert response.status_code == 409


def test_in_app_alerts_are_user_scoped_and_acknowledgeable(tmp_path) -> None:
    client, _, _, _, _ = _secured_client(tmp_path)
    investor_a = _login(client, "investor-a@example.com", INVESTOR_PASSWORD)
    investor_b = _login(client, "investor-b@example.com", INVESTOR_PASSWORD)
    store = client.app.state.alert_store
    message = AlertMessage(
        user_id=client.app.state.authentication.store.get_user_by_email(
            "investor-a@example.com"
        ).user_id,
        snapshot_identifier="alert:decision:test",
        as_of=datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
        topics=(AlertTopic.CIO_DECISION,),
        priority=AlertPriority.STANDARD,
        subject="Capital Intelligence update",
        body="The portfolio warrants review.",
        channels=(AlertChannel.IN_APP,),
    )
    delivery = store.enqueue(message, AlertChannel.IN_APP)
    AlertDeliveryService(store).dispatch_pending()

    listing = client.get("/v1/alerts", headers=_headers(investor_a))
    assert listing.status_code == 200
    assert listing.json()["unread"] == 1
    assert listing.json()["items"][0]["delivery_id"] == delivery.delivery_id
    assert listing.json()["items"][0]["event_identifier"] == "alert:decision:test"
    assert "snapshot_identifier" not in listing.json()["items"][0]

    hidden = client.post(
        f"/v1/alerts/{delivery.delivery_id}/acknowledge",
        headers=_headers(investor_b),
    )
    assert hidden.status_code == 404

    acknowledged = client.post(
        f"/v1/alerts/{delivery.delivery_id}/acknowledge",
        headers=_headers(investor_a),
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert client.get(
        "/v1/alerts", headers=_headers(investor_a)
    ).json()["unread"] == 0
