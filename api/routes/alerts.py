"""Authenticated alert preferences and in-app delivery history."""

from __future__ import annotations

from datetime import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.config import ApiSettings
from api.dependencies import get_settings, require_principal
from delivery import (
    AlertPreference,
    AlertTopic,
    DeliveryChannel,
    SQLiteDeliveryStore,
)
from security import AuthenticatedPrincipal


router = APIRouter(prefix="/v1/alerts", tags=["alerts"])


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone_name: str = "UTC"
    delivery_time: str = "08:00"
    enabled_topics: list[AlertTopic]
    channels: list[DeliveryChannel]
    email_address: str | None = None
    conviction_threshold: int = Field(default=5, ge=1, le=100)


def _store(settings: ApiSettings) -> SQLiteDeliveryStore:
    return SQLiteDeliveryStore(settings.identity_database.parent / "delivery.db")


def _record(record) -> dict[str, object]:
    return {
        "delivery_id": record.delivery_id,
        "cycle_id": record.cycle_id,
        "topic": record.topic.value,
        "channel": record.channel.value,
        "status": record.status.value,
        "headline": record.headline,
        "explanation": record.explanation,
        "attempts": record.attempts,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "sent_at": None if record.sent_at is None else record.sent_at.isoformat(),
        "acknowledged_at": None if record.acknowledged_at is None else record.acknowledged_at.isoformat(),
        "last_error": record.last_error,
    }


@router.get("/preferences")
def get_preferences(
    principal: AuthenticatedPrincipal = Depends(require_principal),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    preference = _store(settings).preference(principal.user_id)
    if preference is None:
        return {
            "user_id": principal.user_id,
            "investor_identifier": principal.investor_identifier or principal.user_id,
            "configured": False,
        }
    return {
        "user_id": preference.user_id,
        "investor_identifier": preference.investor_identifier,
        "timezone_name": preference.timezone_name,
        "delivery_time": preference.delivery_time.isoformat(timespec="minutes"),
        "enabled_topics": sorted(item.value for item in preference.enabled_topics),
        "channels": sorted(item.value for item in preference.channels),
        "email_address": preference.email_address,
        "conviction_threshold": preference.conviction_threshold,
        "configured": True,
    }


@router.put("/preferences")
def update_preferences(
    update: PreferenceUpdate,
    principal: AuthenticatedPrincipal = Depends(require_principal),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    investor_identifier = principal.investor_identifier or principal.user_id
    try:
        delivery_time = time.fromisoformat(update.delivery_time)
        preference = AlertPreference(
            user_id=principal.user_id,
            investor_identifier=investor_identifier,
            timezone_name=update.timezone_name,
            delivery_time=delivery_time,
            enabled_topics=frozenset(update.enabled_topics),
            channels=frozenset(update.channels),
            email_address=update.email_address,
            conviction_threshold=update.conviction_threshold,
        )
        _store(settings).set_preference(preference)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return get_preferences(principal, settings)


@router.get("")
def alert_history(
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_principal),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    items = _store(settings).history(user_id=principal.user_id, limit=limit)
    return {"items": [_record(item) for item in items], "total": len(items)}


@router.post("/{delivery_id}/acknowledge")
def acknowledge_alert(
    delivery_id: str,
    principal: AuthenticatedPrincipal = Depends(require_principal),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, object]:
    try:
        record = _store(settings).acknowledge(delivery_id, user_id=principal.user_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert was not found") from error
    return _record(record)


__all__ = ["router"]
