"""Versioned API routers."""

from api.routes.alerts import router as alerts_router
from api.routes.authentication import router as authentication_router
from api.routes.business_cycle import router as business_cycle_router
from api.routes.credit_cycle import router as credit_cycle_router
from api.routes.daily import router as daily_router
from api.routes.decisions import router as decisions_router
from api.routes.environment import router as environment_router
from api.routes.health import router as health_router
from api.routes.liquidity import router as liquidity_router
from api.routes.market_breadth import router as market_breadth_router
from api.routes.objectives import router as objectives_router
from api.routes.operations import router as operations_router
from api.routes.personal import router as personal_router
from api.routes.personal_cio_history import router as personal_cio_history_router
from api.routes.portfolios import router as portfolios_router
from api.routes.replays import router as replays_router
from api.routes.users import router as users_router

__all__ = [
    "alerts_router",
    "authentication_router",
    "business_cycle_router",
    "credit_cycle_router",
    "daily_router",
    "decisions_router",
    "environment_router",
    "health_router",
    "liquidity_router",
    "market_breadth_router",
    "objectives_router",
    "operations_router",
    "personal_router",
    "personal_cio_history_router",
    "portfolios_router",
    "replays_router",
    "users_router",
]
