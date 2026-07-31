"""Controlled paper universe for listed and direct liquid-market opportunities.

Listed securities use authenticated Alpaca paper/IEX evidence. Direct spot FX,
direct spot crypto, and fully collateralized futures use a separate public,
point-in-time paper evidence adapter. Every instrument remains subject to the
same canonical CIO, construction, authorization, simulation, and portfolio
controls. Real-money order routing is never authorized here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateAssetClass
from governance import AssetClassApprovalState, TradingSessionModel
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from providers.alpaca_paper import (
    AlpacaPaperClient,
    AlpacaPaperProviderError,
    AlpacaPaperSettings,
    create_alpaca_paper_client,
)


DEFAULT_UNIVERSE_PATH = Path("config/free_paper_pilot_universe.json")
SUPPORTED_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.US_ETF,
        CandidateAssetClass.CASH_EQUIVALENT,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
    }
)
DIRECT_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
    }
)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return round(normalized, 12)


@dataclass(frozen=True, slots=True)
class FreePaperPilotInstrument:
    symbol: str
    instrument_identifier: str
    name: str
    execution_asset_class: CandidateAssetClass
    economic_exposure: str
    venue: str
    country_code: str
    currency: str
    instrument_type: str
    maximum_weight: float
    issuer_cik: str | None = None
    provider_symbol: str | None = None
    settlement_currency: str | None = None
    contract_multiplier: float = 1.0
    trading_session_model: TradingSessionModel | None = None
    quote_spread_bps: float = 5.0

    def __post_init__(self) -> None:
        for field_name in (
            "symbol",
            "instrument_identifier",
            "name",
            "economic_exposure",
            "venue",
            "country_code",
            "currency",
            "instrument_type",
        ):
            value = _text(getattr(self, field_name), field_name=field_name)
            if field_name in {"symbol", "venue", "country_code", "currency"}:
                value = value.upper()
            elif field_name in {"economic_exposure", "instrument_type"}:
                value = value.lower()
            object.__setattr__(self, field_name, value)
        if self.execution_asset_class not in SUPPORTED_EXECUTION_CLASSES:
            raise ValueError("paper instrument has an unsupported execution asset class")
        direct = self.execution_asset_class in DIRECT_EXECUTION_CLASSES
        if direct:
            if self.instrument_type not in {"spot", "token", "future"}:
                raise ValueError("direct paper instruments must be spot, token, or future")
            if self.provider_symbol is None or not str(self.provider_symbol).strip():
                raise ValueError("direct paper instruments require provider_symbol")
            object.__setattr__(self, "provider_symbol", str(self.provider_symbol).strip())
            settlement = str(self.settlement_currency or "USD").strip().upper()
            if settlement != "USD" or self.currency != "USD":
                raise ValueError("initial direct paper instruments must quote and settle in USD")
            object.__setattr__(self, "settlement_currency", settlement)
            if not isinstance(self.trading_session_model, TradingSessionModel):
                raise ValueError("direct paper instruments require a trading session model")
            if self.execution_asset_class is CandidateAssetClass.CRYPTO:
                if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_7:
                    raise ValueError("direct crypto must use continuous 24/7 sessions")
            elif self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_5:
                raise ValueError("direct FX and futures must use continuous 24/5 sessions")
        else:
            if self.country_code != "US" or self.currency != "USD":
                raise ValueError("listed paper instruments must be U.S.-listed and USD-denominated")
            if self.instrument_type not in {"common_stock", "preferred_stock", "fund"}:
                raise ValueError("listed paper instruments must be stocks or funds")
            object.__setattr__(self, "settlement_currency", "USD")
            object.__setattr__(self, "trading_session_model", TradingSessionModel.EXCHANGE_LOCAL)
        if self.issuer_cik is not None:
            normalized_cik = str(self.issuer_cik).strip()
            if not normalized_cik.isdigit():
                raise ValueError("issuer_cik must contain only digits")
            object.__setattr__(self, "issuer_cik", normalized_cik.zfill(10))
        if isinstance(self.contract_multiplier, bool) or not isinstance(
            self.contract_multiplier, (int, float)
        ) or float(self.contract_multiplier) <= 0:
            raise ValueError("contract_multiplier must be positive")
        object.__setattr__(self, "contract_multiplier", float(self.contract_multiplier))
        if isinstance(self.quote_spread_bps, bool) or not isinstance(
            self.quote_spread_bps, (int, float)
        ) or float(self.quote_spread_bps) <= 0:
            raise ValueError("quote_spread_bps must be positive")
        object.__setattr__(self, "quote_spread_bps", float(self.quote_spread_bps))
        object.__setattr__(
            self,
            "maximum_weight",
            _number(
                self.maximum_weight,
                field_name="maximum_weight",
                minimum=0.000001,
                maximum=1.0,
            ),
        )

    def profile(self, *, universe_identifier: str) -> MultiAssetInstrumentProfile:
        if self.execution_asset_class is CandidateAssetClass.FX:
            custody = "prime-broker-spot-fx-paper.v1"
            execution = "direct-spot-fx-simulated-fill.v1"
        elif self.execution_asset_class is CandidateAssetClass.CRYPTO:
            custody = "qualified-digital-asset-paper-custody.v1"
            execution = "direct-spot-crypto-simulated-fill.v1"
        elif self.execution_asset_class is CandidateAssetClass.FUTURE:
            custody = "futures-clearing-fully-collateralized-paper.v1"
            execution = "direct-future-simulated-fill.v1"
        else:
            custody = "alpaca-paper-broker-custody.v1"
            execution = "alpaca-paper-iex-simulated-fill.v1"
        return MultiAssetInstrumentProfile(
            symbol=self.symbol,
            instrument_identifier=self.instrument_identifier,
            asset_class=self.execution_asset_class,
            venue=self.venue,
            country_code=self.country_code,
            price_currency=self.currency,
            settlement_currency=self.settlement_currency or self.currency,
            approval_identifier=f"core-policy:{universe_identifier}",
            approval_state=AssetClassApprovalState.PAPER_ELIGIBLE,
            unlevered=True,
            spot_only=self.execution_asset_class is not CandidateAssetClass.FUTURE,
            custody_settlement_identifier=custody,
            execution_model_version=execution,
            instrument_type=self.instrument_type,
            gross_leverage=1.0,
            defined_risk=True,
            margin_required=False,
            contract_multiplier=self.contract_multiplier,
            contract_model_version=(
                "fully-collateralized-continuous-future-contract.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else None
            ),
            margin_model_version=(
                "fully-collateralized-notional-no-margin-leverage.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else None
            ),
            lifecycle_model_version=(
                "continuous-future-expiry-lifecycle.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else None
            ),
            roll_model_version=(
                "continuous-future-explicit-roll-research.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else None
            ),
            trading_session_model=self.trading_session_model,
        )



@dataclass(frozen=True, slots=True)
class FreePaperPilotUniverse:
    identifier: str
    objective: str
    portfolio_code: str
    reporting_currency: str
    quote_provider: str
    execution_mode: str
    minimum_cash_weight: float
    maximum_batch_turnover: float
    maximum_single_instrument_weight: float
    maximum_crypto_proxy_weight: float
    maximum_volatility_proxy_weight: float
    maximum_quote_age_minutes: int
    required_exposure_classes: tuple[str, ...]
    instruments: tuple[FreePaperPilotInstrument, ...]
    limitations: tuple[str, ...]
    schema_version: str = "free-paper-pilot-universe.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "objective",
            "portfolio_code",
            "reporting_currency",
            "quote_provider",
            "execution_mode",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if self.portfolio_code != "COMPOUNDING":
            raise ValueError("free paper pilot must target COMPOUNDING")
        if self.reporting_currency.upper() != "USD":
            raise ValueError("free paper pilot reporting currency must be USD")
        for field_name in (
            "minimum_cash_weight",
            "maximum_batch_turnover",
            "maximum_single_instrument_weight",
            "maximum_crypto_proxy_weight",
            "maximum_volatility_proxy_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name),
            )
        if isinstance(self.maximum_quote_age_minutes, bool) or not isinstance(
            self.maximum_quote_age_minutes,
            int,
        ):
            raise TypeError("maximum_quote_age_minutes must be an integer")
        if self.maximum_quote_age_minutes < 1:
            raise ValueError("maximum_quote_age_minutes must be positive")
        if not isinstance(self.instruments, tuple) or not self.instruments:
            raise ValueError("free paper pilot requires instruments")
        symbols = tuple(item.symbol for item in self.instruments)
        identifiers = tuple(item.instrument_identifier for item in self.instruments)
        exposures = tuple(item.economic_exposure for item in self.instruments)
        if len(symbols) != len(set(symbols)):
            raise ValueError("free paper pilot symbols must be unique")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("free paper pilot instrument identifiers must be unique")
        required = set(self.required_exposure_classes)
        if required != set(exposures):
            missing = sorted(required - set(exposures))
            extra = sorted(set(exposures) - required)
            raise ValueError(
                f"free paper pilot exposure coverage must be exact: missing={missing} extra={extra}"
            )
        if any(
            item.maximum_weight > self.maximum_single_instrument_weight
            for item in self.instruments
            if item.economic_exposure not in {"cash_treasury"}
        ):
            raise ValueError("instrument maximum exceeds pilot single-instrument limit")
        crypto = tuple(
            item for item in self.instruments
            if item.execution_asset_class is CandidateAssetClass.CRYPTO
            or item.economic_exposure == "crypto"
        )
        if any(item.maximum_weight > self.maximum_crypto_proxy_weight for item in crypto):
            raise ValueError("crypto instrument exceeds the pilot limit")
        volatility = self.instrument_for_exposure("volatility")
        if volatility.maximum_weight > self.maximum_volatility_proxy_weight:
            raise ValueError("volatility proxy exceeds the pilot limit")

    @property
    def symbol_map(self) -> dict[str, FreePaperPilotInstrument]:
        return {item.symbol: item for item in self.instruments}

    def instrument_for_exposure(self, exposure: str) -> FreePaperPilotInstrument:
        normalized = _text(exposure, field_name="exposure").lower()
        return next(item for item in self.instruments if item.economic_exposure == normalized)

    def profiles(self) -> tuple[MultiAssetInstrumentProfile, ...]:
        return tuple(
            item.profile(universe_identifier=self.identifier)
            for item in self.instruments
        )

    def profiles_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for item in self.profiles():
            value = asdict(item)
            value["asset_class"] = item.asset_class.value
            value["approval_state"] = item.approval_state.value
            value["trading_session_model"] = (
                None
                if item.trading_session_model is None
                else item.trading_session_model.value
            )
            payload.append(value)
        return payload


@dataclass(frozen=True, slots=True)
class FreePaperPilotReadinessReport:
    evaluated_at: datetime
    universe_identifier: str
    configuration_ready: bool
    execution_ready_now: bool
    market_open: bool
    account_status: str
    validated_symbols: tuple[str, ...]
    quote_timestamps: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evaluated_at"] = self.evaluated_at.isoformat()
        payload["quote_timestamps"] = [list(item) for item in self.quote_timestamps]
        payload["fingerprint"] = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return payload


def _free_paper_pilot_universe_from_payload(
    payload: Mapping[str, Any],
) -> FreePaperPilotUniverse:
    """Build a governed paper universe directly from a validated mapping."""

    if not isinstance(payload, Mapping):
        raise ValueError("free paper pilot universe must be a JSON object")
    if payload.get("schema_version") != "free-paper-pilot-universe.v1":
        raise ValueError("unsupported free paper pilot universe schema")
    raw_instruments = payload.get("instruments")
    if not isinstance(raw_instruments, list):
        raise ValueError("free paper pilot instruments must be a JSON array")
    instruments = tuple(
        FreePaperPilotInstrument(
            symbol=str(item["symbol"]),
            instrument_identifier=str(item["instrument_identifier"]),
            name=str(item["name"]),
            execution_asset_class=CandidateAssetClass(
                str(item["execution_asset_class"])
            ),
            economic_exposure=str(item["economic_exposure"]),
            venue=str(item["venue"]),
            country_code=str(item["country_code"]),
            currency=str(item["currency"]),
            settlement_currency=(None if item.get("settlement_currency") in {None, ""} else str(item["settlement_currency"])),
            instrument_type=str(item["instrument_type"]),
            maximum_weight=float(item["maximum_weight"]),
            issuer_cik=(None if item.get("issuer_cik") in {None, ""} else str(item["issuer_cik"])),
            provider_symbol=(None if item.get("provider_symbol") in {None, ""} else str(item["provider_symbol"])),
            contract_multiplier=float(item.get("contract_multiplier", 1.0)),
            trading_session_model=(None if item.get("trading_session_model") in {None, ""} else TradingSessionModel(str(item["trading_session_model"]))),
            quote_spread_bps=float(item.get("quote_spread_bps", 5.0)),
        )
        for item in raw_instruments
        if isinstance(item, Mapping)
    )
    if len(instruments) != len(raw_instruments):
        raise ValueError("every free paper pilot instrument must be an object")
    return FreePaperPilotUniverse(
        identifier=str(payload["identifier"]),
        objective=str(payload["objective"]),
        portfolio_code=str(payload["portfolio_code"]),
        reporting_currency=str(payload["reporting_currency"]),
        quote_provider=str(payload["quote_provider"]),
        execution_mode=str(payload["execution_mode"]),
        minimum_cash_weight=float(payload["minimum_cash_weight"]),
        maximum_batch_turnover=float(payload["maximum_batch_turnover"]),
        maximum_single_instrument_weight=float(
            payload["maximum_single_instrument_weight"]
        ),
        maximum_crypto_proxy_weight=float(payload["maximum_crypto_proxy_weight"]),
        maximum_volatility_proxy_weight=float(
            payload["maximum_volatility_proxy_weight"]
        ),
        maximum_quote_age_minutes=int(payload["maximum_quote_age_minutes"]),
        required_exposure_classes=tuple(
            str(item) for item in payload["required_exposure_classes"]
        ),
        instruments=instruments,
        limitations=tuple(str(item) for item in payload["limitations"]),
        schema_version=str(payload["schema_version"]),
    )


def load_free_paper_pilot_universe(
    path: str | Path = DEFAULT_UNIVERSE_PATH,
) -> FreePaperPilotUniverse:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load free paper pilot universe {str(source)!r}") from error
    return _free_paper_pilot_universe_from_payload(payload)


def free_paper_pilot_universe_payload(
    universe: FreePaperPilotUniverse,
) -> dict[str, Any]:
    """Serialize a governed static or dynamically discovered paper universe."""

    if not isinstance(universe, FreePaperPilotUniverse):
        raise TypeError("universe must be FreePaperPilotUniverse")
    return {
        "schema_version": universe.schema_version,
        "identifier": universe.identifier,
        "objective": universe.objective,
        "portfolio_code": universe.portfolio_code,
        "reporting_currency": universe.reporting_currency,
        "quote_provider": universe.quote_provider,
        "execution_mode": universe.execution_mode,
        "minimum_cash_weight": universe.minimum_cash_weight,
        "maximum_batch_turnover": universe.maximum_batch_turnover,
        "maximum_single_instrument_weight": universe.maximum_single_instrument_weight,
        "maximum_crypto_proxy_weight": universe.maximum_crypto_proxy_weight,
        "maximum_volatility_proxy_weight": universe.maximum_volatility_proxy_weight,
        "maximum_quote_age_minutes": universe.maximum_quote_age_minutes,
        "required_exposure_classes": list(universe.required_exposure_classes),
        "instruments": [
            {
                "symbol": item.symbol,
                "instrument_identifier": item.instrument_identifier,
                "name": item.name,
                "execution_asset_class": item.execution_asset_class.value,
                "economic_exposure": item.economic_exposure,
                "venue": item.venue,
                "country_code": item.country_code,
                "currency": item.currency,
                "settlement_currency": item.settlement_currency,
                "instrument_type": item.instrument_type,
                "maximum_weight": item.maximum_weight,
                "issuer_cik": item.issuer_cik,
                "provider_symbol": item.provider_symbol,
                "contract_multiplier": item.contract_multiplier,
                "trading_session_model": (None if item.trading_session_model is None else item.trading_session_model.value),
                "quote_spread_bps": item.quote_spread_bps,
            }
            for item in universe.instruments
        ],
        "limitations": list(universe.limitations),
    }


def active_paper_universe_path() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_ACTIVE_PAPER_UNIVERSE", "").strip()
    if configured:
        return Path(configured).expanduser()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_dir / "active-paper-universe.json"


def write_active_paper_universe(
    universe: FreePaperPilotUniverse,
    *,
    eligible_universe_publication_identifier: str,
    destination: str | Path | None = None,
) -> Path:
    path = Path(destination).expanduser() if destination is not None else active_paper_universe_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "eligible_universe_publication_identifier": _text(
            eligible_universe_publication_identifier,
            field_name="eligible_universe_publication_identifier",
        ),
        "universe": free_paper_pilot_universe_payload(universe),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_execution_paper_universe(
    construction: Mapping[str, Any],
    *,
    fallback_path: str | Path = DEFAULT_UNIVERSE_PATH,
    active_path: str | Path | None = None,
) -> FreePaperPilotUniverse:
    """Resolve the exact daily universe used by an executable construction."""

    publication_identifier = str(
        construction.get("eligible_universe_publication_identifier", "")
    ).strip()
    path = Path(active_path).expanduser() if active_path is not None else active_paper_universe_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(payload, Mapping)
                and str(payload.get("eligible_universe_publication_identifier", "")).strip()
                == publication_identifier
                and isinstance(payload.get("universe"), Mapping)
            ):
                return _free_paper_pilot_universe_from_payload(payload["universe"])
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return load_free_paper_pilot_universe(fallback_path)


def assess_free_paper_pilot_readiness(
    *,
    universe: FreePaperPilotUniverse,
    client: AlpacaPaperClient,
    evaluated_at: datetime | None = None,
) -> FreePaperPilotReadinessReport:
    if not isinstance(universe, FreePaperPilotUniverse):
        raise TypeError("universe must be FreePaperPilotUniverse")
    if not isinstance(client, AlpacaPaperClient):
        raise TypeError("client must be AlpacaPaperClient")
    dynamic_evaluation_time = evaluated_at is None
    now = evaluated_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    blockers: list[str] = []
    warnings = list(universe.limitations)
    validated: list[str] = []
    quote_times: list[tuple[str, str]] = []
    execution_blocks: list[str] = []
    account_status = "unavailable"
    market_open = False

    try:
        account = client.account()
        account_status = str(account.get("status", "unavailable")).upper()
        if account_status != "ACTIVE":
            blockers.append("Alpaca paper account is not ACTIVE")
        if account.get("trading_blocked") is True or account.get("account_blocked") is True:
            blockers.append("Alpaca paper account is blocked")
    except (AlpacaPaperProviderError, TypeError, ValueError) as error:
        blockers.append(f"Alpaca paper account check failed: {error}")

    try:
        clock = client.clock()
        market_open = clock.get("is_open") is True
        if not market_open:
            warnings.append("The U.S. market is currently closed; configuration may be ready but execution is held.")
    except (AlpacaPaperProviderError, TypeError, ValueError) as error:
        blockers.append(f"Alpaca market clock check failed: {error}")

    for instrument in universe.instruments:
        try:
            asset = client.asset(instrument.symbol)
            if str(asset.get("status", "")).lower() != "active":
                raise ValueError("asset is not active")
            if asset.get("tradable") is not True:
                raise ValueError("asset is not tradable")
            if asset.get("fractionable") is not True:
                raise ValueError("asset is not fractionable")
            if str(asset.get("class", "us_equity")).lower() not in {
                "us_equity",
                "equity",
            }:
                raise ValueError("asset is not a U.S. listed equity security")
            validated.append(instrument.symbol)
        except (AlpacaPaperProviderError, TypeError, ValueError) as error:
            blockers.append(f"{instrument.symbol}: Alpaca asset validation failed: {error}")

    if len(validated) == len(universe.instruments):
        try:
            quotes = client.latest_quotes(validated)
            quote_reference_time = now
            if dynamic_evaluation_time:
                # Live provider timestamps are validated against Alpaca's own
                # post-collection market clock rather than the hosted runner's
                # potentially lagging wall clock. Explicit point-in-time
                # evaluations remain strict and immutable.
                now = datetime.now(timezone.utc)
                provider_clock = client.clock()
                provider_timestamp = datetime.fromisoformat(
                    str(provider_clock["timestamp"]).replace("Z", "+00:00")
                )
                if (
                    provider_timestamp.tzinfo is None
                    or provider_timestamp.utcoffset() is None
                ):
                    raise ValueError("Alpaca market clock timestamp lacks an offset")
                provider_timestamp = provider_timestamp.astimezone(timezone.utc)
                if abs((provider_timestamp - now).total_seconds()) > 900:
                    raise ValueError(
                        "Alpaca market clock differs from the runtime clock by more than 15 minutes"
                    )
                quote_reference_time = provider_timestamp
                market_open = provider_clock.get("is_open") is True
            maximum_age = timedelta(minutes=universe.maximum_quote_age_minutes)
            for symbol in validated:
                quote = quotes[symbol]
                bid = float(quote["bp"])
                ask = float(quote["ap"])
                if bid <= 0.0 or ask <= 0.0:
                    if market_open:
                        execution_blocks.append(
                            f"{symbol}: IEX top of book is not executable"
                        )
                    else:
                        warnings.append(
                            f"{symbol}: closed-market IEX top of book is not executable; execution remains held"
                        )
                elif ask < bid:
                    execution_blocks.append(f"{symbol}: IEX quote is crossed")
                observed = datetime.fromisoformat(
                    str(quote["t"]).replace("Z", "+00:00")
                )
                if observed.tzinfo is None or observed.utcoffset() is None:
                    raise ValueError(f"{symbol} quote timestamp lacks an offset")
                if not dynamic_evaluation_time and observed > quote_reference_time:
                    raise ValueError(f"{symbol} quote is future-known")
                if observed > now:
                    warnings.append(
                        f"{symbol}: quote source timestamp differs from the runtime clock but was received live and is normalized to response-time availability"
                    )
                quote_times.append((symbol, observed.isoformat()))
                effective_observed = min(observed, quote_reference_time)
                if market_open and quote_reference_time - effective_observed > maximum_age:
                    execution_blocks.append(
                        f"{symbol}: live quote is older than {universe.maximum_quote_age_minutes} minutes"
                    )
        except (AlpacaPaperProviderError, KeyError, TypeError, ValueError) as error:
            execution_blocks.append(f"Alpaca IEX quote validation failed: {error}")

    warnings.extend(
        f"Execution held: {detail}" for detail in dict.fromkeys(execution_blocks)
    )
    configuration_ready = not blockers
    execution_ready_now = configuration_ready and market_open and not execution_blocks
    return FreePaperPilotReadinessReport(
        evaluated_at=now,
        universe_identifier=universe.identifier,
        configuration_ready=configuration_ready,
        execution_ready_now=execution_ready_now,
        market_open=market_open,
        account_status=account_status,
        validated_symbols=tuple(sorted(validated)),
        quote_timestamps=tuple(sorted(quote_times)),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def validate_pilot_construction(
    construction: Mapping[str, Any],
    *,
    universe: FreePaperPilotUniverse,
) -> None:
    if not isinstance(construction, Mapping):
        raise TypeError("construction must be a mapping")
    if construction.get("status") in {"blocked", "no_action"}:
        raise ValueError("construction is not executable")
    if construction.get("blocks"):
        raise ValueError("construction contains implementation blocks")
    turnover = float(construction.get("turnover", 0.0))
    if turnover > universe.maximum_batch_turnover + 1e-9:
        raise ValueError(
            f"pilot turnover {turnover:.2%} exceeds {universe.maximum_batch_turnover:.2%}"
        )
    allowed = set(universe.symbol_map)
    trades = construction.get("trades")
    if not isinstance(trades, list) or not trades:
        raise ValueError("construction contains no paper trades")
    trade_symbols = {str(item.get("symbol", "")).upper() for item in trades if isinstance(item, Mapping)}
    unknown = sorted(trade_symbols - allowed)
    if unknown:
        raise ValueError(f"construction contains instruments outside the free pilot: {unknown}")
    targets = construction.get("target_weights")
    if not isinstance(targets, list):
        raise ValueError("construction target_weights must be a list")
    total_target = 0.0
    for item in targets:
        if not isinstance(item, Mapping):
            raise ValueError("target weight entries must be objects")
        symbol = str(item.get("symbol", "")).upper()
        weight = float(item.get("weight", 0.0))
        total_target += weight
        instrument = universe.symbol_map.get(symbol)
        if instrument is not None and weight > instrument.maximum_weight + 1e-9:
            raise ValueError(
                f"{symbol} target {weight:.2%} exceeds pilot limit {instrument.maximum_weight:.2%}"
            )
    cash_weight = float(construction.get("target_cash_weight", 0.0))
    if cash_weight < universe.minimum_cash_weight - 1e-9:
        raise ValueError(
            f"pilot cash target {cash_weight:.2%} is below {universe.minimum_cash_weight:.2%}"
        )
    if total_target + cash_weight > 1.0 + 1e-8:
        raise ValueError("construction target weights and cash exceed 100%")


def write_pilot_profiles(
    universe: FreePaperPilotUniverse,
    destination: str | Path,
) -> Path:
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(universe.profiles_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def default_alpaca_client() -> AlpacaPaperClient:
    return create_alpaca_paper_client()


__all__ = [
    "DEFAULT_UNIVERSE_PATH",
    "FreePaperPilotInstrument",
    "FreePaperPilotReadinessReport",
    "FreePaperPilotUniverse",
    "assess_free_paper_pilot_readiness",
    "default_alpaca_client",
    "active_paper_universe_path",
    "free_paper_pilot_universe_payload",
    "load_execution_paper_universe",
    "load_free_paper_pilot_universe",
    "validate_pilot_construction",
    "write_active_paper_universe",
    "write_pilot_profiles",
]
