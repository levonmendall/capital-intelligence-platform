"""FastAPI dependency accessors."""

from fastapi import Request

from api.config import ApiSettings
from api.repositories import ApiResources


def get_settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def get_resources(request: Request) -> ApiResources:
    return request.app.state.resources


__all__ = ["get_resources", "get_settings"]
