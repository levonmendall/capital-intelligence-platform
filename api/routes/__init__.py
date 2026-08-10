"""Versioned API routers."""

from api.routes.alerts import router as alerts_router
from api.routes.ask_cio import router as ask_cio_router
from api.routes.authentication import router as authentication_router
from api.routes.business_cycle import router as business_cycle_router
from api.routes.credit_cycle import router as credit_cycle_router
from api.routes.cio import router as cio_router
from api.routes.cio_diagnostic import router as cio_diagnostic_router
from api.routes.daily import router as daily_router
from api.routes.decisions import router as decisions_router
from api.routes.environment import router as environment_router
from api.routes.governance import router as governance_router
from api.routes.health import router as health_router
from api.routes.liquidity import router as liquidity_router
from api.routes.market_breadth import router as market_breadth_router
from api.routes.normalization import router as normalization_router
from api.routes.operations import router as operations_router
from api.routes.portfolios import router as portfolios_router
from api.routes.provider_validation import router as provider_validation_router
from api.routes.replays import router as replays_router
from api.routes.risk import router as risk_router
from api.routes.synthesis import router as synthesis_router
from api.routes.technical_momentum import router as technical_momentum_router
from api.routes.users import router as users_router
from api.routes.valuation import router as valuation_router

__all__ = [
    "alerts_router",
    "ask_cio_router",
    "authentication_router",
    "business_cycle_router",
    "credit_cycle_router",
    "cio_router",
    "cio_diagnostic_router",
    "daily_router",
    "decisions_router",
    "environment_router",
    "governance_router",
    "health_router",
    "liquidity_router",
    "market_breadth_router",
    "normalization_router",
    "operations_router",
    "portfolios_router",
    "provider_validation_router",
    "replays_router",
    "risk_router",
    "synthesis_router",
    "technical_momentum_router",
    "users_router",
    "valuation_router",
]
