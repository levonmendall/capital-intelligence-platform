"""Authentication session routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import (
    get_authentication,
    get_bearer_token,
    require_principal,
)
from api.identity_views import token_pair_to_dict, user_account_to_dict
from api.schemas import (
    CurrentUserResponse,
    ErrorResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from security import (
    AuthenticatedPrincipal,
    AuthenticationService,
    InvalidCredentialsError,
)


router = APIRouter(prefix="/v1/auth", tags=["authentication"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
)
def login(
    payload: LoginRequest,
    request: Request,
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    try:
        tokens = authentication.store.login(
            email=payload.email,
            password=payload.password,
            ip_address=(request.client.host if request.client is not None else None),
            user_agent=request.headers.get("user-agent"),
        )
    except (InvalidCredentialsError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return token_pair_to_dict(tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
)
def refresh(
    payload: RefreshRequest,
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    try:
        tokens = authentication.store.refresh(payload.refresh_token)
    except (InvalidCredentialsError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return token_pair_to_dict(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    token: str | None = Depends(get_bearer_token),
    principal: AuthenticatedPrincipal = Depends(require_principal),
    authentication: AuthenticationService = Depends(get_authentication),
) -> None:
    del principal
    if token is not None:
        authentication.store.logout(token)


@router.get("/me", response_model=CurrentUserResponse)
def current_user(
    principal: AuthenticatedPrincipal = Depends(require_principal),
    authentication: AuthenticationService = Depends(get_authentication),
) -> dict[str, object]:
    if not authentication.required:
        return {
            "user_id": principal.user_id,
            "email": principal.email,
            "display_name": principal.display_name,
            "investor_identifier": principal.investor_identifier,
            "is_active": True,
            "roles": [role.value for role in sorted(principal.roles, key=lambda item: item.value)],
            "mandates": [],
            "investor_access": [],
            "created_at": "1970-01-01T00:00:00+00:00",
        }
    return user_account_to_dict(authentication.store.get_user(principal.user_id))


__all__ = ["router"]
