"""Administrator-only user, mandate, and investor-access management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_authentication, require_roles
from api.identity_views import user_account_to_dict
from api.schemas import (
    AssignInvestorRequest,
    AssignMandateRequest,
    CreateUserRequest,
    CurrentUserResponse,
    ErrorResponse,
    UserListResponse,
)
from security import (
    AuthenticationService,
    IdentityConflictError,
    InvestorPermission,
    MandatePermission,
    UserRole,
)


router = APIRouter(
    prefix="/v1/users",
    tags=["users"],
    dependencies=[Depends(require_roles(UserRole.ADMINISTRATOR))],
)


@router.get("", response_model=UserListResponse)
def users(
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    accounts = authentication.store.list_users()
    return {
        "items": [user_account_to_dict(account) for account in accounts],
        "total": len(accounts),
    }


@router.post(
    "",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def create_user(
    payload: CreateUserRequest,
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    try:
        account = authentication.store.create_user(
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            investor_identifier=payload.investor_identifier,
            roles=tuple(UserRole(role) for role in payload.roles),
        )
    except IdentityConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    return user_account_to_dict(account)


@router.post(
    "/{user_id}/mandates",
    response_model=CurrentUserResponse,
    responses={404: {"model": ErrorResponse}},
)
def assign_mandate(
    user_id: str,
    payload: AssignMandateRequest,
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    try:
        account = authentication.store.assign_mandate(
            user_id,
            payload.mandate_code,
            MandatePermission(payload.permission),
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="user was not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return user_account_to_dict(account)


@router.post(
    "/{user_id}/investor-access",
    response_model=CurrentUserResponse,
    responses={404: {"model": ErrorResponse}},
)
def assign_investor_access(
    user_id: str,
    payload: AssignInvestorRequest,
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    try:
        account = authentication.store.grant_investor_access(
            user_id,
            payload.investor_identifier,
            InvestorPermission(payload.permission),
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="user was not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return user_account_to_dict(account)


@router.post(
    "/{user_id}/disable",
    response_model=CurrentUserResponse,
    responses={404: {"model": ErrorResponse}},
)
def disable_user(
    user_id: str,
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    try:
        account = authentication.store.disable_user(user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="user was not found") from error
    return user_account_to_dict(account)


__all__ = ["router"]
