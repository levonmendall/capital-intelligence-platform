from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    record_manual_cio_diagnostic_progress,
    request_manual_cio_diagnostic,
)
from providers.databento_options import DatabentoOptionsError
from providers.massive_options import (
    MassiveOptionBar,
    MassiveOptionDefinition,
    MassiveOptionSelection,
)
from providers.redundant_options import RedundantOptionsProvider


AS_OF = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)


class _CappedPrimary:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise DatabentoOptionsError(
            "Databento OPRA HTTP 402",
            status_code=402,
            retryable=False,
        )


class _BudgetAwareFallback:
    configured = True

    def __init__(self) -> None:
        self.kwargs = None

    def select_contracts(self, *_args, **kwargs):
        self.kwargs = kwargs
        expiration = AS_OF + timedelta(days=60)
        definition = MassiveOptionDefinition(
            symbol="SPY261010C00650000",
            raw_symbol="O:SPY261010C00650000",
            underlying="SPY",
            option_right="call",
            expiration_at=expiration,
            strike=650.0,
            contract_multiplier=100.0,
            session_date=date(2026, 8, 11),
            source_identifier=(
                "massive-opra-definition:2026-08-11:O:SPY261010C00650000"
            ),
        )
        bar = MassiveOptionBar(
            raw_symbol=definition.raw_symbol,
            observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
            close=12.7,
            volume=120.0,
            source_identifier=(
                "massive-opra-bar:O:SPY261010C00650000:"
                "2026-08-10T20:00:00+00:00"
            ),
        )
        return (MassiveOptionSelection(definition=definition, bar=bar),)


def test_massive_fallback_bounds_free_tier_expiration_requests() -> None:
    fallback = _BudgetAwareFallback()
    provider = RedundantOptionsProvider(primary=_CappedPrimary(), fallback=fallback)

    selections = provider.select_contracts(
        "SPY",
        underlying_price=640.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=365,
        maximum_expirations=3,
        candidates_per_bucket=8,
    )

    assert selections
    assert fallback.kwargs is not None
    assert fallback.kwargs["maximum_expirations"] == 1
    assert fallback.kwargs["candidates_per_bucket"] == 1
    assert fallback.kwargs["minimum_days_to_expiry"] == 30
    assert fallback.kwargs["maximum_days_to_expiry"] == 365


def test_legacy_databento_progress_stage_publishes_provider_neutral_name(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }
    _request, created = request_manual_cio_diagnostic(
        requested_by="test",
        now=AS_OF,
        values=values,
    )
    assert created is True
    claimed = claim_manual_cio_diagnostic(now=AS_OF, values=values)
    assert claimed is not None

    progress = record_manual_cio_diagnostic_progress(
        "catalog_databento_options",
        metrics={"configured_underlyings": 20},
        values=values,
    )

    assert progress is not None
    assert progress.progress_stage == "catalog_options"
    assert progress.detail is not None
    assert progress.detail.startswith("governed_progress=catalog_options")

    completed = record_manual_cio_diagnostic_progress(
        "catalog_databento_options_complete",
        metrics={"catalog_records": 40},
        values=values,
    )
    assert completed is not None
    assert completed.progress_stage == "catalog_options_complete"


def test_render_blueprint_declares_massive_options_secret() -> None:
    blueprint = Path("render.yaml").read_text(encoding="utf-8")
    assert (
        "- key: CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY\n"
        "        sync: false"
    ) in blueprint
