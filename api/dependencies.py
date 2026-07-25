"""FastAPI dependency accessors and authorization guards."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.config import ApiSettings
from api.repositories import ApiResources
from security import (
    AuthenticatedPrincipal,
    AuthenticationService,
    InvalidCredentialsError,
    UserRole,
)


_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def get_resources(request: Request) -> ApiResources:
    return request.app.state.resources


def get_authentication(request: Request) -> AuthenticationService:
    return request.app.state.authentication


def get_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    if credentials is None:
        return None
    if credentials.scheme.casefold() != "bearer":
        return None
    return credentials.credentials


def require_principal(
    token: str | None = Depends(get_bearer_token),
    authentication: AuthenticationService = Depends(get_authentication),
) -> AuthenticatedPrincipal:
    try:
        return authentication.principal_for_access_token(token)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication is required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def require_roles(*roles: UserRole) -> Callable[..., AuthenticatedPrincipal]:
    required = frozenset(roles)
    if not required:
        raise ValueError("at least one role is required")

    def dependency(
        principal: AuthenticatedPrincipal = Depends(require_principal),
    ) -> AuthenticatedPrincipal:
        if principal.is_administrator or principal.roles.intersection(required):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="the authenticated user lacks the required role",
        )

    return dependency


__all__ = [
    "get_authentication",
    "get_bearer_token",
    "get_resources",
    "get_settings",
    "require_principal",
    "require_roles",
]
