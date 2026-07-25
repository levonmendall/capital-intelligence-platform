"""Versioned API routers."""

from api.routes.daily import router as daily_router
from api.routes.decisions import router as decisions_router
from api.routes.environment import router as environment_router
from api.routes.health import router as health_router
from api.routes.portfolios import router as portfolios_router
from api.routes.replays import router as replays_router

__all__ = [
    "daily_router",
    "decisions_router",
    "environment_router",
    "health_router",
    "portfolios_router",
    "replays_router",
]
