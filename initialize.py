"""Initialize active Capital Intelligence data stores and binding market scope."""

from __future__ import annotations

import json
import os

from api.config import ApiSettings
from market_scope import load_global_market_scope
from operations.provider_validation import (
    ProviderValidationReport,
    require_provider_validation,
    validate_live_providers,
    write_provider_validation_report,
)
from portfolio.constants import (
    CANONICAL_PORTFOLIO_CODE,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.initialization import (
    PortfolioInitializationError,
    initialize_canonical_portfolio,
)

_PROVIDER_SECRET_ENV_VARS = (
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
    "EODHD_API_TOKEN",
    "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
    "DATABENTO_API_KEY",
)


def _enabled(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _credential_configured(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def _sanitize_provider_detail(detail: str) -> str:
    sanitized = str(detail)
    for name in _PROVIDER_SECRET_ENV_VARS:
        secret = os.getenv(name, "").strip()
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


def _log_provider_validation_diagnostics(
    report: ProviderValidationReport,
) -> None:
    """Print credential-safe failure details before fail-closed startup exit."""

    if report.ready:
        return
    credential_presence = {
        "databento_api_key_configured": _credential_configured(
            "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY",
            "DATABENTO_API_KEY",
        ),
        "eodhd_api_token_configured": _credential_configured(
            "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
            "EODHD_API_TOKEN",
        ),
    }
    print(
        "Provider validation credential presence: "
        + json.dumps(credential_presence, sort_keys=True)
    )
    for check in report.checks:
        if not check.required or check.passed:
            continue
        payload = {
            "check": check.name,
            "detail": _sanitize_provider_detail(check.detail),
            "provider": check.provider,
            "required": check.required,
            "state": check.state,
        }
        print(
            "Provider validation failure detail: "
            + json.dumps(payload, sort_keys=True)
        )


def _initialize_portfolio(settings: ApiSettings) -> None:
    try:
        result = initialize_canonical_portfolio(
            settings.portfolio_database,
            persistence_root=settings.portfolio_database.parent,
        )
    except PortfolioInitializationError as error:
        print(
            "Canonical portfolio initialization: "
            + json.dumps(
                {
                    "portfolio_failure_detail": error.detail,
                    "portfolio_failure_type": error.failure_type.value,
                    "portfolio_initialization_state": "invalid",
                },
                sort_keys=True,
            )
        )
        raise

    print(
        "Canonical portfolio initialization: "
        + json.dumps(
            {
                "portfolio_initialization_state": result.initialization_state.value,
                "portfolio_schema_version": result.schema_version,
                "portfolio_state_generation_id": result.state_generation_id,
                "portfolio_state_hash": result.state_hash,
            },
            sort_keys=True,
        )
    )
    print(
        f"Canonical portfolio {CANONICAL_PORTFOLIO_CODE} initialized at "
        f"{settings.portfolio_database} with ${INITIAL_PAPER_CAPITAL:,.2f}."
    )


def main() -> None:
    print("Initializing Capital Intelligence Platform...")
    settings = ApiSettings.from_env()
    scope = load_global_market_scope()
    scope.require_complete_analysis_scope()
    _initialize_portfolio(settings)
    print(
        f"Global market analysis scope validated across "
        f"{len(scope.markets)} governed market families."
    )
    if _enabled("CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP"):
        report = validate_live_providers()
        report_path = write_provider_validation_report(report)
        print(
            "Live provider validation "
            f"{'passed' if report.ready else 'failed'} for release {report.release}; "
            f"report={report_path}."
        )
        _log_provider_validation_diagnostics(report)
        if _enabled("CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_REQUIRED"):
            require_provider_validation(report)


if __name__ == "__main__":
    main()
