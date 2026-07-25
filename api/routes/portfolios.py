"""Mandate-authorized virtual portfolio routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_resources, require_principal
from api.repositories import ApiResources
from api.schemas import ErrorResponse, PortfolioListResponse
from security import AuthenticatedPrincipal


router = APIRouter(prefix="/v1/portfolios", tags=["portfolios"])


@router.get("", response_model=PortfolioListResponse)
def portfolios(
    resources: ApiResources = Depends(get_resources),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> PortfolioListResponse:
    items = [
        item
        for item in resources.portfolios.list()
        if principal.can_access_mandate(str(item["code"]))
    ]
    return PortfolioListResponse(items=items, total=len(items))


@router.get(
    "/{portfolio_code}",
    response_model=dict[str, Any],
    responses={404: {"model": ErrorResponse}},
)
def portfolio(
    portfolio_code: str,
    resources: ApiResources = Depends(get_resources),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, Any]:
    if not principal.can_access_mandate(portfolio_code):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="portfolio was not found",
        )
    payload = resources.portfolios.get(portfolio_code)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="portfolio was not found",
        )
    return payload
