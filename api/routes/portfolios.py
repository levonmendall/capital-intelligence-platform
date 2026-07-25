"""Read-only virtual portfolio routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_resources
from api.repositories import ApiResources
from api.schemas import ErrorResponse, PortfolioListResponse

router = APIRouter(prefix="/v1/portfolios", tags=["portfolios"])


@router.get("", response_model=PortfolioListResponse)
def portfolios(
    resources: ApiResources = Depends(get_resources),
) -> PortfolioListResponse:
    items = list(resources.portfolios.list())
    return PortfolioListResponse(items=items, total=len(items))


@router.get(
    "/{portfolio_code}",
    response_model=dict[str, Any],
    responses={404: {"model": ErrorResponse}},
)
def portfolio(
    portfolio_code: str,
    resources: ApiResources = Depends(get_resources),
) -> dict[str, Any]:
    payload = resources.portfolios.get(portfolio_code)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="portfolio was not found",
        )
    return payload
