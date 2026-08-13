from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations.resumable_options_discovery import ResumableOptionsProvider
from providers.massive_options import MassiveOptionsError
from providers.redundant_options import RedundantOptionsProvider
from providers.tradier_market_data import TradierMarketDataError


NOW = datetime(2026, 8, 13, 18, 17, tzinfo=timezone.utc)
EXPIRATION = NOW + timedelta(days=30)


class _PrimaryOptions:
    def definitions(
        self,
        underlying,
        *,
        underlying_price,
        as_of,
        minimum_days_to_expiry,
        maximum_days_to_expiry,
    ):
        assert underlying == "SPY"
        assert underlying_price == 500.0
        assert minimum_days_to_expiry == 7
        assert maximum_days_to_expiry == 60
        return tuple(
            SimpleNamespace(
                symbol=f"option:SPY:{right}",
                raw_symbol=f"SPY260912{code}00500000",
                underlying="SPY",
                option_right=right,
                expiration_at=EXPIRATION,
                strike=500.0,
                contract_multiplier=100.0,
                session_date=as_of.date(),
                source_identifier=f"alpaca-definition:{right}",
            )
            for right, code in (("call", "C"), ("put", "P"))
        )

    def latest_daily_bars(self, identifiers, *, as_of, history_days):
        assert history_days in {10, 365}
        symbols = tuple(raw_symbol for _instrument_id, raw_symbol in identifiers)
        return (
            as_of.date(),
            {
                symbol: (
                    SimpleNamespace(
                        raw_symbol=symbol,
                        observed_at=as_of - timedelta(days=1),
                        close=12.5,
                        volume=1000.0,
                        source_identifier=f"alpaca-bar:{symbol}:{history_days}",
                    ),
                )
                for symbol in symbols
            },
        )


class _Delegate:
    configured = True
    primary_configured = True
    secondary_configured = False
    fallback_configured = False
    primary = _PrimaryOptions()


class _PrimaryNoHistory:
    configured = True

    def latest_daily_bars(self, identifiers, *, as_of, history_days):
        return as_of.date(), {}


class _TradierHistoryFailure:
    configured = True

    def daily_history(self, symbol, *, as_of, history_days):
        raise TradierMarketDataError("Tradier history response is missing daily bars")


class _MassiveHistoryFailure:
    configured = True

    def latest_daily_bars(self, instruments, *, as_of, history_days):
        raise MassiveOptionsError("Massive OPRA daily bars are unavailable")


def test_registered_progress_stages_allow_resumable_option_provider_path(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED", "true"
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RENDER_GIT_COMMIT", "test-resumable-options-release")

    selections = ResumableOptionsProvider(delegate=_Delegate()).select_contracts(
        "SPY",
        underlying_price=500.0,
        as_of=NOW,
        minimum_days_to_expiry=7,
        maximum_days_to_expiry=60,
        maximum_expirations=2,
        candidates_per_bucket=2,
    )

    assert len(selections) == 2
    assert {item.definition.option_right for item in selections} == {"call", "put"}
    checkpoint_root = tmp_path / "all-market-certification" / "options"
    assert tuple(checkpoint_root.rglob("definitions.json"))
    assert tuple(checkpoint_root.rglob("expiration-*.json"))


def test_successful_primary_no_history_is_not_reclassified_as_provider_outage() -> None:
    provider = RedundantOptionsProvider(
        primary=_PrimaryNoHistory(),
        secondary=_TradierHistoryFailure(),
        fallback=_MassiveHistoryFailure(),
    )

    session, bars = provider.latest_daily_bars(
        ((None, "SPY260918C00650000"),),
        as_of=NOW,
        history_days=365,
    )

    assert session == NOW.date()
    assert bars == {}
