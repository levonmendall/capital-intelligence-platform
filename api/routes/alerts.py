"""Authenticated alert preferences, inbox, and acknowledgement routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.dependencies import get_alert_store, get_settings, require_principal
from api.config import ApiSettings
from api.schemas import (
    AlertDeliveryListResponse,
    AlertDeliveryResponse,
    AlertPreferenceRequest,
    AlertPreferenceResponse,
)
from delivery import (
    AlertChannel,
    AlertTopic,
    DeliveryPreference,
    SQLiteAlertStore,
)
from security import AuthenticatedPrincipal


router = APIRouter(prefix="/v1/alerts", tags=["alerts"])


def _preference_payload(preference: DeliveryPreference) -> AlertPreferenceResponse:
    return AlertPreferenceResponse(
        user_id=preference.user_id,
        timezone_name=preference.timezone_name,
        delivery_hour=preference.delivery_hour,
        channels=[value.value for value in preference.channels],
        topics=[value.value for value in preference.topics],
        email_address=preference.email_address,
        minimum_conviction_change=preference.minimum_conviction_change,
        updated_at=(None if preference.updated_at is None else preference.updated_at.isoformat()),
    )


def _delivery_payload(delivery) -> AlertDeliveryResponse:
    return AlertDeliveryResponse(
        delivery_id=delivery.delivery_id,
        snapshot_identifier=delivery.snapshot_identifier,
        channel=delivery.channel.value,
        topics=[value.value for value in delivery.topics],
        priority=delivery.priority.value,
        status=delivery.status.value,
        subject=delivery.subject,
        body=delivery.body,
        created_at=delivery.created_at.isoformat(),
        updated_at=delivery.updated_at.isoformat(),
        attempts=delivery.attempts,
        next_attempt_at=(
            None if delivery.next_attempt_at is None else delivery.next_attempt_at.isoformat()
        ),
        sent_at=None if delivery.sent_at is None else delivery.sent_at.isoformat(),
        acknowledged_at=(
            None
            if delivery.acknowledged_at is None
            else delivery.acknowledged_at.isoformat()
        ),
        error=delivery.error,
    )


@router.get("/preferences", response_model=AlertPreferenceResponse)
def get_preferences(
    principal: AuthenticatedPrincipal = Depends(require_principal),
    store: SQLiteAlertStore = Depends(get_alert_store),
) -> AlertPreferenceResponse:
    preference = store.get_preference(
        principal.user_id,
        fallback_email=principal.email,
    )
    return _preference_payload(preference)


@router.put("/preferences", response_model=AlertPreferenceResponse)
def update_preferences(
    payload: AlertPreferenceRequest,
    principal: AuthenticatedPrincipal = Depends(require_principal),
    store: SQLiteAlertStore = Depends(get_alert_store),
    settings: ApiSettings = Depends(get_settings),
) -> AlertPreferenceResponse:
    try:
        channels = tuple(AlertChannel(value) for value in payload.channels)
        topics = tuple(AlertTopic(value) for value in payload.topics)
        if AlertChannel.EMAIL in channels and not settings.smtp_host:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email delivery is not configured for this environment",
            )
        preference = DeliveryPreference(
            user_id=principal.user_id,
            timezone_name=payload.timezone_name,
            delivery_hour=payload.delivery_hour,
            channels=channels,
            topics=topics,
            email_address=payload.email_address,
            minimum_conviction_change=payload.minimum_conviction_change,
        )
        stored = store.save_preference(preference)
    except HTTPException:
        raise
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    return _preference_payload(stored)


@router.get("", response_model=AlertDeliveryListResponse)
def list_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    include_suppressed: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_principal),
    store: SQLiteAlertStore = Depends(get_alert_store),
) -> AlertDeliveryListResponse:
    items = store.list_deliveries(
        principal.user_id,
        limit=limit,
        include_suppressed=include_suppressed,
    )
    return AlertDeliveryListResponse(
        items=[_delivery_payload(item) for item in items],
        total=len(items),
        unread=store.unread_count(principal.user_id),
    )


@router.post(
    "/{delivery_id}/acknowledge",
    response_model=AlertDeliveryResponse,
    responses={404: {"description": "Alert not found"}},
)
def acknowledge_alert(
    delivery_id: str,
    principal: AuthenticatedPrincipal = Depends(require_principal),
    store: SQLiteAlertStore = Depends(get_alert_store),
) -> AlertDeliveryResponse:
    try:
        delivery = store.acknowledge(delivery_id, user_id=principal.user_id)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="alert was not found",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return _delivery_payload(delivery)


__all__ = ["router"]
