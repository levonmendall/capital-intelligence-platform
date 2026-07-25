"""Authenticated access to immutable Personal CIO brief history."""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import ApiSettings
from api.dependencies import get_settings, require_principal
from personal_cio import SQLitePersonalCIOBriefStore
from security import AuthenticatedPrincipal


router = APIRouter(prefix="/v1", tags=["investor objectives"])


@router.get("/personal-cio/{investor_identifier}/history")
def personal_cio_history(
    investor_identifier: str,
    limit: int = Query(default=50, ge=1, le=200),
    settings: ApiSettings = Depends(get_settings),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    if not principal.can_access_investor(investor_identifier):
        raise HTTPException(
            status_code=404,
            detail="Personal CIO brief history was not found",
        )
    path = settings.investor_memory_database.with_name("investment_policy.db")
    if not path.exists():
        return {"items": [], "total": 0}
    items = SQLitePersonalCIOBriefStore(
        path,
        read_only=True,
    ).history(investor_identifier, limit=limit)
    return {"items": list(items), "total": len(items)}


__all__ = ["router"]
