from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations.generalized_reference_readiness import store_asset_reference_component
from operations.persistent_option_reference import (
    PersistentReferenceOptionsProvider,
    _scope,
)
from operations.resumable_options_discovery import _definition_payload
from providers.alpaca_indicative_options import ALPACA_INDICATIVE_OPTIONS_DATASET
from providers.redundant_options import RedundantOptionDefinition


NOW = datetime(2026, 8, 13, 21, 45, tzinfo=timezone.utc)
CAPTURED = NOW - timedelta(minutes=30)
EXPIRATION = NOW + timedelta(days=30)


class _Primary:
    _moneyness_limit = 0.20

    def __init__(self) -> None:
        self.history_days = []

    def definitions(self, *_args, **_kwargs):
        raise AssertionError("live option definitions must not be fetched when reference coverage is complete")

    def latest_daily_bars(self, identifiers, *, as_of, history_days):
        self.history_days.append(history_days)
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
                        source_identifier=f"current-epoch-bar:{symbol}:{history_days}",
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

    def __init__(self) -> None:
        self.primary = _Primary()


def _definition(right: str, code: str) -> RedundantOptionDefinition:
    return RedundantOptionDefinition(
        symbol=f"option:SPY:{right}",
        raw_symbol=f"SPY260912{code}00500000",
        underlying="SPY",
        option_right=right,
        expiration_at=EXPIRATION,
        strike=500.0,
        contract_multiplier=100.0,
        session_date=CAPTURED.date(),
        provider_kind="alpaca_indicative",
        provider_dataset=ALPACA_INDICATIVE_OPTIONS_DATASET,
        provider_stype_in="raw_symbol",
        provider_instrument_id=None,
        source_identifier=f"persistent-definition:{right}",
    )


def test_persistent_definitions_cross_epoch_but_history_does_not(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED", "true"
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RENDER_GIT_COMMIT", "persistent-option-reference-test")
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "persistent-option-reference-test",
    }
    definitions = (_definition("call", "C"), _definition("put", "P"))
    store_asset_reference_component(
        values,
        asset_class=CandidateAssetClass.OPTION,
        scope=_scope("SPY"),
        captured_at=CAPTURED,
        config_fingerprint="reference-envelope-test",
        coverage=("SPY",),
        records=tuple(_definition_payload(item) for item in definitions),
        metadata={
            "collector": "alpaca_indicative_option_chain",
            "reference_only": True,
            "anchor_price": 500.0,
            "reference_moneyness_limit": 0.35,
            "strike_lower": 325.0,
            "strike_upper": 675.0,
            "expiration_gte": (CAPTURED + timedelta(days=1)).date().isoformat(),
            "expiration_lte": (CAPTURED + timedelta(days=68)).date().isoformat(),
        },
    )

    delegate = _Delegate()
    selections = PersistentReferenceOptionsProvider(
        delegate=delegate,
        environ=values,
    ).select_contracts(
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
    assert delegate.primary.history_days == [10, 365]
    exact_epoch_root = tmp_path / "all-market-certification" / "options"
    assert not tuple(exact_epoch_root.rglob("definitions.json"))
    assert tuple(exact_epoch_root.rglob("expiration-*.json"))
    assert all(
        item.bar.source_identifier.startswith("current-epoch-bar:")
        for item in selections
    )
