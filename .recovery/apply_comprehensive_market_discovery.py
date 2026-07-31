from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


def regex_once(content: str, pattern: str, replacement: str, *, label: str, flags: int = 0) -> str:
    result, count = re.subn(pattern, replacement, content, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return result


def patch_free_paper_pilot() -> None:
    path = "operations/free_paper_pilot.py"
    content = read(path)
    content = regex_once(
        content,
        r"SUPPORTED_EXECUTION_CLASSES = frozenset\(\n    \{.*?\n    \}\n\)\nDIRECT_EXECUTION_CLASSES = frozenset\(\n    \{.*?\n    \}\n\)",
        '''SUPPORTED_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.US_ETF,
        CandidateAssetClass.CASH_EQUIVALENT,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.OPTION,
    }
)
DIRECT_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.OPTION,
    }
)''',
        label="expand paper execution classes",
        flags=re.S,
    )
    content = replace_once(
        content,
        "    quote_spread_bps: float = 5.0\n",
        '''    quote_spread_bps: float = 5.0
    provider_kind: str = "alpaca"
    provider_dataset: str | None = None
    provider_stype_in: str | None = None
    expiration_at: str | None = None
    underlying_symbol: str | None = None
    strike: float | None = None
    option_right: str | None = None
''',
        label="add discovered instrument metadata",
    )
    content = regex_once(
        content,
        r"        direct = self\.execution_asset_class in DIRECT_EXECUTION_CLASSES\n.*?        if self\.issuer_cik is not None:",
        '''        direct = self.execution_asset_class in DIRECT_EXECUTION_CLASSES
        if direct:
            allowed_types = {
                CandidateAssetClass.INTERNATIONAL_EQUITY: {"common_stock", "preferred_stock", "fund"},
                CandidateAssetClass.FIXED_INCOME: {"bond"},
                CandidateAssetClass.FX: {"spot"},
                CandidateAssetClass.CRYPTO: {"token", "stablecoin"},
                CandidateAssetClass.FUTURE: {"future"},
                CandidateAssetClass.OPTION: {"option"},
            }[self.execution_asset_class]
            if self.instrument_type not in allowed_types:
                raise ValueError(
                    f"{self.execution_asset_class.value} paper instrument type is unsupported"
                )
            if self.provider_symbol is None or not str(self.provider_symbol).strip():
                raise ValueError("direct paper instruments require provider_symbol")
            object.__setattr__(self, "provider_symbol", str(self.provider_symbol).strip())
            provider_kind = str(self.provider_kind or "yahoo").strip().lower()
            if provider_kind not in {"yahoo", "yahoo_option", "eodhd", "databento"}:
                raise ValueError("unsupported direct market provider kind")
            object.__setattr__(self, "provider_kind", provider_kind)
            if self.provider_dataset is not None:
                object.__setattr__(self, "provider_dataset", str(self.provider_dataset).strip())
            if self.provider_stype_in is not None:
                object.__setattr__(self, "provider_stype_in", str(self.provider_stype_in).strip().lower())
            settlement = str(self.settlement_currency or self.currency).strip().upper()
            object.__setattr__(self, "settlement_currency", settlement)
            if not isinstance(self.trading_session_model, TradingSessionModel):
                raise ValueError("direct paper instruments require a trading session model")
            if self.execution_asset_class is CandidateAssetClass.CRYPTO:
                if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_7:
                    raise ValueError("direct crypto must use continuous 24/7 sessions")
            elif self.execution_asset_class is CandidateAssetClass.FX:
                if self.trading_session_model is not TradingSessionModel.CONTINUOUS_24_5:
                    raise ValueError("direct FX must use continuous 24/5 sessions")
            elif self.execution_asset_class is CandidateAssetClass.FIXED_INCOME:
                if self.trading_session_model is not TradingSessionModel.DEALER_24_5:
                    raise ValueError("direct bonds must use dealer 24/5 sessions")
            if self.execution_asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION}:
                if self.expiration_at is None or not str(self.expiration_at).strip():
                    raise ValueError("dated derivative instruments require expiration_at")
                object.__setattr__(self, "expiration_at", str(self.expiration_at).strip())
            if self.execution_asset_class is CandidateAssetClass.OPTION:
                if self.underlying_symbol is None or not str(self.underlying_symbol).strip():
                    raise ValueError("defined-risk options require underlying_symbol")
                if self.option_right not in {"call", "put"}:
                    raise ValueError("defined-risk options require call or put option_right")
                if isinstance(self.strike, bool) or not isinstance(self.strike, (int, float)) or float(self.strike) <= 0:
                    raise ValueError("defined-risk options require a positive strike")
                object.__setattr__(self, "underlying_symbol", str(self.underlying_symbol).strip().upper())
                object.__setattr__(self, "strike", float(self.strike))
        else:
            object.__setattr__(self, "provider_kind", "alpaca")
            if self.country_code != "US" or self.currency != "USD":
                raise ValueError("listed Alpaca paper instruments must be U.S.-listed and USD-denominated")
            if self.instrument_type not in {"common_stock", "preferred_stock", "fund"}:
                raise ValueError("listed paper instruments must be stocks or funds")
            object.__setattr__(self, "settlement_currency", "USD")
            object.__setattr__(self, "trading_session_model", TradingSessionModel.EXCHANGE_LOCAL)
        if self.issuer_cik is not None:''',
        label="replace direct instrument validation",
        flags=re.S,
    )
    profile = '''    def profile(self, *, universe_identifier: str) -> MultiAssetInstrumentProfile:
        if self.execution_asset_class is CandidateAssetClass.FX:
            custody = "prime-broker-spot-fx-paper.v2"
            execution = "direct-spot-fx-simulated-fill.v2"
        elif self.execution_asset_class is CandidateAssetClass.CRYPTO:
            custody = "qualified-digital-asset-paper-custody.v2"
            execution = "direct-spot-crypto-simulated-fill.v2"
        elif self.execution_asset_class is CandidateAssetClass.FUTURE:
            custody = "futures-clearing-fully-collateralized-paper.v2"
            execution = "dated-future-simulated-fill.v2"
        elif self.execution_asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY:
            custody = "global-security-paper-custody.v1"
            execution = "direct-global-equity-simulated-fill.v1"
        elif self.execution_asset_class is CandidateAssetClass.FIXED_INCOME:
            custody = "book-entry-direct-bond-paper-custody.v1"
            execution = "direct-bond-simulated-fill.v1"
        elif self.execution_asset_class is CandidateAssetClass.OPTION:
            custody = "options-clearing-long-premium-paper.v1"
            execution = "defined-risk-option-simulated-fill.v1"
        else:
            custody = "alpaca-paper-broker-custody.v1"
            execution = "alpaca-paper-iex-simulated-fill.v1"
        derivative = self.execution_asset_class in {
            CandidateAssetClass.FUTURE,
            CandidateAssetClass.OPTION,
        }
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
            spot_only=self.execution_asset_class in {
                CandidateAssetClass.FX,
                CandidateAssetClass.CRYPTO,
            },
            custody_settlement_identifier=custody,
            execution_model_version=execution,
            instrument_type=self.instrument_type,
            gross_leverage=1.0,
            defined_risk=True,
            margin_required=False,
            contract_multiplier=self.contract_multiplier,
            contract_model_version=(
                "dated-exchange-future-contract.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else "long-premium-option-contract.v1"
                if self.execution_asset_class is CandidateAssetClass.OPTION
                else None
            ),
            margin_model_version=(
                "fully-collateralized-notional-no-margin-leverage.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else "premium-paid-upfront-no-margin-borrowing.v1"
                if self.execution_asset_class is CandidateAssetClass.OPTION
                else None
            ),
            lifecycle_model_version=(
                "dated-future-expiry-settlement-lifecycle.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else "defined-risk-option-expiry-exercise-lifecycle.v1"
                if self.execution_asset_class is CandidateAssetClass.OPTION
                else "direct-bond-coupon-maturity-lifecycle.v1"
                if self.execution_asset_class is CandidateAssetClass.FIXED_INCOME
                else None
            ),
            roll_model_version=(
                "dated-future-liquidity-and-expiry-roll.v1"
                if self.execution_asset_class is CandidateAssetClass.FUTURE
                else None
            ),
            trading_session_model=self.trading_session_model,
        )
'''
    content = regex_once(
        content,
        r"    def profile\(self, \*, universe_identifier: str\) -> MultiAssetInstrumentProfile:\n.*?(?=\n\n\n@dataclass\(frozen=True, slots=True\)\nclass FreePaperPilotUniverse)",
        profile.rstrip(),
        label="replace profile construction",
        flags=re.S,
    )
    parser_anchor = '''            quote_spread_bps=float(item.get("quote_spread_bps", 5.0)),
        )'''
    parser_replacement = '''            quote_spread_bps=float(item.get("quote_spread_bps", 5.0)),
            provider_kind=str(item.get("provider_kind", "alpaca")),
            provider_dataset=(None if item.get("provider_dataset") in {None, ""} else str(item["provider_dataset"])),
            provider_stype_in=(None if item.get("provider_stype_in") in {None, ""} else str(item["provider_stype_in"])),
            expiration_at=(None if item.get("expiration_at") in {None, ""} else str(item["expiration_at"])),
            underlying_symbol=(None if item.get("underlying_symbol") in {None, ""} else str(item["underlying_symbol"])),
            strike=(None if item.get("strike") is None else float(item["strike"])),
            option_right=(None if item.get("option_right") in {None, ""} else str(item["option_right"])),
        )'''
    content = replace_once(
        content,
        parser_anchor,
        parser_replacement,
        label="parse discovery metadata",
    )
    serializer_anchor = '''                "quote_spread_bps": item.quote_spread_bps,
            }'''
    serializer_replacement = '''                "quote_spread_bps": item.quote_spread_bps,
                "provider_kind": item.provider_kind,
                "provider_dataset": item.provider_dataset,
                "provider_stype_in": item.provider_stype_in,
                "expiration_at": item.expiration_at,
                "underlying_symbol": item.underlying_symbol,
                "strike": item.strike,
                "option_right": item.option_right,
            }'''
    content = replace_once(
        content,
        serializer_anchor,
        serializer_replacement,
        label="serialize discovery metadata",
    )
    write(path, content)


def patch_direct_global_markets() -> None:
    path = "operations/direct_global_markets.py"
    content = read(path)
    content = replace_once(content, "import json\n", "import json\nimport os\n", label="import os")
    content = regex_once(
        content,
        r"DIRECT_EXECUTION_CLASSES = frozenset\(\n    \{.*?\}\n\)",
        '''DIRECT_EXECUTION_CLASSES = frozenset(
    {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.OPTION,
    }
)''',
        label="expand direct classes",
        flags=re.S,
    )
    content = replace_once(
        content,
        'DEFAULT_CHART_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"\n',
        'DEFAULT_CHART_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"\nDEFAULT_EODHD_BASE_URL = "https://eodhd.com/api"\n',
        label="add eodhd endpoint",
    )
    content = replace_once(
        content,
        '            raise ValueError("direct-market universe may contain only FX, crypto, and futures")',
        '            raise ValueError("direct-market universe contains an unsupported direct discovery class")',
        label="update direct universe error",
    )
    loader_anchor = '''            quote_spread_bps=float(item.get("quote_spread_bps", 5.0)),
        )'''
    loader_replacement = '''            quote_spread_bps=float(item.get("quote_spread_bps", 5.0)),
            provider_kind=str(item.get("provider_kind", "yahoo")),
            provider_dataset=(None if item.get("provider_dataset") in {None, ""} else str(item["provider_dataset"])),
            provider_stype_in=(None if item.get("provider_stype_in") in {None, ""} else str(item["provider_stype_in"])),
            expiration_at=(None if item.get("expiration_at") in {None, ""} else str(item["expiration_at"])),
            underlying_symbol=(None if item.get("underlying_symbol") in {None, ""} else str(item["underlying_symbol"])),
            strike=(None if item.get("strike") is None else float(item["strike"])),
            option_right=(None if item.get("option_right") in {None, ""} else str(item["option_right"])),
        )'''
    content = replace_once(content, loader_anchor, loader_replacement, label="load direct metadata")
    content = replace_once(
        content,
        '''        chart_base_url: str = DEFAULT_CHART_BASE_URL,
        timeout_seconds: int = 15,
    ) -> None:''',
        '''        chart_base_url: str = DEFAULT_CHART_BASE_URL,
        eodhd_base_url: str = DEFAULT_EODHD_BASE_URL,
        eodhd_api_token: str | None = None,
        timeout_seconds: int = 15,
    ) -> None:''',
        label="extend direct client init signature",
    )
    content = replace_once(
        content,
        '''        self.chart_base_url = chart_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds''',
        '''        self.chart_base_url = chart_base_url.rstrip("/")
        self.eodhd_base_url = eodhd_base_url.rstrip("/")
        self.eodhd_api_token = (
            eodhd_api_token
            or os.getenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN")
            or os.getenv("EODHD_API_KEY")
            or os.getenv("EODHD_API_TOKEN")
        )
        self.timeout_seconds = timeout_seconds''',
        label="initialize direct provider settings",
    )
    content = replace_once(
        content,
        '''        params: dict[str, object] = {
            "interval": interval,''',
        '''        if instrument.provider_kind == "eodhd":
            return self._eodhd_chart(
                instrument,
                interval=interval,
                range_value=range_value,
                start=start,
                end=end,
            )
        params: dict[str, object] = {
            "interval": interval,''',
        label="route eodhd charts",
    )
    content = replace_once(
        content,
        '''        url = f"{self.chart_base_url}/{urlquote(instrument.provider_symbol or instrument.symbol, safe='')}"''',
        '''        provider_symbol = (
            instrument.underlying_symbol
            if instrument.execution_asset_class is CandidateAssetClass.OPTION
            and interval == "1d"
            and start is not None
            else instrument.provider_symbol or instrument.symbol
        )
        url = f"{self.chart_base_url}/{urlquote(provider_symbol, safe='')}"''',
        label="use option underlying history",
    )
    eodhd_method = '''
    def _eodhd_chart(
        self,
        instrument: FreePaperPilotInstrument,
        *,
        interval: str,
        range_value: str | None,
        start: datetime | None,
        end: datetime | None,
    ) -> Mapping[str, Any]:
        if not self.eodhd_api_token:
            raise DirectGlobalMarketError("EODHD direct-market token is unavailable")
        symbol = instrument.provider_symbol or instrument.symbol
        if interval == "5m" and range_value is not None:
            path = f"/real-time/{urlquote(symbol, safe='')}"
            params = {"api_token": self.eodhd_api_token, "fmt": "json"}
            try:
                response = self.http_get(
                    self.eodhd_base_url + path,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if int(getattr(response, "status_code", 0)) != 200:
                    raise DirectGlobalMarketError("EODHD real-time quote is unavailable")
                payload = response.json()
                price = payload.get("close", payload.get("previousClose"))
                raw_time = payload.get("timestamp")
                if price is None or raw_time is None:
                    raise DirectGlobalMarketError("EODHD real-time quote is incomplete")
                return {
                    "timestamp": [int(raw_time)],
                    "indicators": {"quote": [{"close": [float(price)], "volume": [float(payload.get("volume") or 0.0)]}]},
                }
            except (requests.RequestException, TypeError, ValueError) as error:
                raise DirectGlobalMarketError("EODHD real-time request failed") from error
        if start is None or end is None:
            raise ValueError("EODHD history requires start and end")
        params = {
            "api_token": self.eodhd_api_token,
            "fmt": "json",
            "period": "d",
            "order": "a",
            "from": _aware(start, field_name="start").date().isoformat(),
            "to": _aware(end, field_name="end").date().isoformat(),
        }
        try:
            response = self.http_get(
                self.eodhd_base_url + f"/eod/{urlquote(symbol, safe='')}",
                params=params,
                timeout=self.timeout_seconds,
            )
            if int(getattr(response, "status_code", 0)) != 200:
                raise DirectGlobalMarketError("EODHD history is unavailable")
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise DirectGlobalMarketError("EODHD history request failed") from error
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise DirectGlobalMarketError("EODHD history response is invalid")
        timestamps: list[int] = []
        closes: list[float] = []
        volumes: list[float] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            try:
                observed = datetime.fromisoformat(str(item["date"])[:10]).replace(tzinfo=timezone.utc)
                close = float(item.get("adjusted_close", item["close"]))
                volume = float(item.get("volume") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            if close > 0.0:
                timestamps.append(int(observed.timestamp()))
                closes.append(close)
                volumes.append(max(0.0, volume))
        if not timestamps:
            raise DirectGlobalMarketError("EODHD history contains no usable rows")
        return {
            "timestamp": timestamps,
            "indicators": {"quote": [{"close": closes, "volume": volumes}]},
        }

    def fx_rate_to_usd(self, currency: str) -> tuple[float, datetime]:
        normalized = str(currency).strip().upper()
        now = datetime.now(timezone.utc)
        if normalized == "USD":
            return 1.0, now
        for symbol, invert in ((f"{normalized}USD=X", False), (f"USD{normalized}=X", True)):
            synthetic = FreePaperPilotInstrument(
                symbol=f"FX{normalized}USD",
                instrument_identifier=f"instrument:fx-translation:{normalized}-usd",
                name=f"{normalized} / USD translation",
                execution_asset_class=CandidateAssetClass.FX,
                economic_exposure="foreign_exchange",
                venue="GLOBAL_FX",
                country_code="GLOBAL",
                currency="USD",
                settlement_currency="USD",
                instrument_type="spot",
                maximum_weight=0.000001,
                provider_symbol=symbol,
                provider_kind="yahoo",
                trading_session_model=TradingSessionModel.CONTINUOUS_24_5,
            )
            try:
                rows = self._rows(self._chart(synthetic, interval="5m", range_value="5d"))
            except DirectGlobalMarketError:
                continue
            if rows:
                price = _positive(rows[-1]["c"], field_name="FX translation")
                observed = _timestamp(rows[-1]["t"], field_name="FX translation timestamp")
                return ((1.0 / price) if invert else price), observed
        raise DirectGlobalMarketError(f"USD translation is unavailable for {normalized}")
'''
    content = replace_once(
        content,
        "    @staticmethod\n    def _rows(result: Mapping[str, Any]) -> tuple[dict[str, object], ...]:",
        eodhd_method + "\n    @staticmethod\n    def _rows(result: Mapping[str, Any]) -> tuple[dict[str, object], ...]:",
        label="add direct provider and fx methods",
    )
    content = regex_once(
        content,
        r"    @staticmethod\n    def session_is_open\(\n        instrument: FreePaperPilotInstrument,\n        \*,\n        as_of: datetime,\n    \) -> bool:\n.*?        return False",
        '''    @staticmethod
    def session_is_open(
        instrument: FreePaperPilotInstrument,
        *,
        as_of: datetime,
    ) -> bool:
        now = _aware(as_of, field_name="as_of")
        model = instrument.trading_session_model
        if model is TradingSessionModel.CONTINUOUS_24_7:
            return True
        weekday = now.weekday()
        if model in {TradingSessionModel.CONTINUOUS_24_5, TradingSessionModel.DEALER_24_5}:
            if weekday < 4:
                return True
            if weekday == 4:
                return now.hour < 22
            if weekday == 6:
                return now.hour >= 22
            return False
        if weekday >= 5:
            return False
        windows = {
            "LSE": (7, 17), "XETRA": (7, 17), "PA": (7, 17), "AS": (7, 17),
            "BR": (7, 17), "SW": (7, 16), "TSE": (0, 7), "HK": (1, 9),
            "AU": (0, 7), "ASX": (0, 7), "NSE": (3, 11), "BSE": (3, 11),
            "SG": (1, 9), "KO": (0, 7), "WAR": (7, 16), "SA": (13, 21),
            "MX": (14, 22), "TO": (13, 21), "V": (13, 21), "OPRA": (13, 21),
        }
        start, end = windows.get(instrument.venue, (0, 22))
        return start <= now.hour < end''',
        label="expand session models",
        flags=re.S,
    )
    content = replace_once(
        content,
        '                f"{profile.symbol} is not a direct FX, crypto, or futures instrument"',
        '                f"{profile.symbol} is outside the governed direct discovery classes"',
        label="session provider message",
    )
    content = replace_once(
        content,
        '''            result[profile.symbol] = MultiAssetQuote(
                symbol=profile.symbol,''',
        '''            fx_rate, fx_observed_at = self.client.fx_rate_to_usd(profile.price_currency)
            result[profile.symbol] = MultiAssetQuote(
                symbol=profile.symbol,''',
        label="resolve fx quote translation",
    )
    content = replace_once(
        content,
        '''                price_currency=profile.price_currency,
                fx_rate_to_base=1.0,
                fx_observed_at=observed,''',
        '''                price_currency=profile.price_currency,
                fx_rate_to_base=fx_rate,
                fx_observed_at=min(fx_observed_at, timestamp),''',
        label="apply fx translation",
    )
    content = replace_once(
        content,
        '                fx_source_identifier="usd-base-rate:1.0",',
        '                fx_source_identifier=f"direct-fx-translation:{profile.price_currency}:USD",',
        label="update fx source",
    )
    content = replace_once(
        content,
        '    "DEFAULT_DIRECT_UNIVERSE_PATH",\n',
        '    "DEFAULT_DIRECT_UNIVERSE_PATH",\n    "DEFAULT_EODHD_BASE_URL",\n',
        label="export eodhd endpoint",
    )
    write(path, content)


def patch_production_evidence() -> None:
    path = "production_paper_evidence.py"
    content = read(path)
    content = replace_once(
        content,
        '''    DirectGlobalMarketClient,
)''',
        '''    DirectGlobalMarketClient,
    DirectGlobalMarketUniverse,
)''',
        label="import dynamic direct universe",
    )
    content = replace_once(
        content,
        '''    if direct_instruments:
        direct_client = DirectGlobalMarketClient()
        direct_symbols = tuple(item.symbol for item in direct_instruments)''',
        '''    if direct_instruments:
        direct_client = DirectGlobalMarketClient(
            DirectGlobalMarketUniverse(
                identifier=f"dynamic-direct-evidence:{universe.identifier}",
                provider_identifier="comprehensive-direct-market-evidence.v1",
                instruments=direct_instruments,
                limitations=universe.limitations,
            )
        )
        direct_symbols = tuple(item.symbol for item in direct_instruments)''',
        label="use dynamic direct client universe",
    )
    content = replace_once(
        content,
        '''    replication_method = {CandidateAssetClass.FX: "direct-spot-fx-paper", CandidateAssetClass.CRYPTO: "direct-spot-crypto-paper", CandidateAssetClass.FUTURE: "direct-fully-collateralized-future-paper"}.get(instrument.execution_asset_class, "us-listed-economic-exposure-wrapper")''',
        '''    replication_method = {
        CandidateAssetClass.INTERNATIONAL_EQUITY: "direct-global-equity-paper",
        CandidateAssetClass.FIXED_INCOME: "direct-bond-paper",
        CandidateAssetClass.FX: "direct-spot-fx-paper",
        CandidateAssetClass.CRYPTO: "direct-spot-crypto-paper",
        CandidateAssetClass.FUTURE: "direct-dated-fully-collateralized-future-paper",
        CandidateAssetClass.OPTION: "direct-long-premium-defined-risk-option-paper",
    }.get(instrument.execution_asset_class, "us-listed-economic-exposure-wrapper")''',
        label="expand replication methods",
    )
    content = replace_once(
        content,
        '''    candidate = CandidateDecisionRecord(
        identifier=candidate_identifier,''',
        '''    horizon_days = 365
    if instrument.expiration_at:
        try:
            expiry = _aware(
                datetime.fromisoformat(instrument.expiration_at.replace("Z", "+00:00")),
                field_name="instrument expiration",
            )
            horizon_days = max(7, min(365, (expiry - as_of).days))
        except ValueError as error:
            raise ProductionPaperEvidenceError(
                f"{instrument.symbol} expiration is invalid"
            ) from error
    candidate = CandidateDecisionRecord(
        identifier=candidate_identifier,''',
        label="derive dated decision horizon",
    )
    content = replace_once(
        content,
        "        decision_horizon_days=365,\n",
        "        decision_horizon_days=horizon_days,\n",
        label="use dated decision horizon",
    )
    content = replace_once(
        content,
        '''            uses_derivatives=(instrument.execution_asset_class is CandidateAssetClass.FUTURE or instrument.economic_exposure in {"managed_futures", "option_strategies", "volatility"}),''',
        '''            uses_derivatives=(instrument.execution_asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION} or instrument.economic_exposure in {"managed_futures", "option_strategies", "volatility"}),''',
        label="mark options as derivatives",
    )
    content = replace_once(
        content,
        '''            f"{features.bar_count} authenticated point-in-time IEX daily bars",''',
        '''            f"{features.bar_count} point-in-time daily market bars with provider lineage",''',
        label="generalize evidence text",
    )
    content = replace_once(
        content,
        '''            (f"ALPACA_IEX:{instrument.symbol}", features.latest_observed_at.isoformat()),''',
        '''            (
                f"{'DIRECT_MARKET' if direct_market else 'ALPACA_IEX'}:{instrument.symbol}",
                features.latest_observed_at.isoformat(),
            ),''',
        label="generalize source lineage",
    )
    write(path, content)


def patch_production_context() -> None:
    path = "production_context_publication_governed.py"
    content = read(path)
    content = content.replace("from operations.direct_global_markets import load_direct_global_market_universe\n", "")
    content = replace_once(
        content,
        '''from operations.equity_discovery import (
    EquityDiscoveryResult,
    discover_us_equities,
)''',
        '''from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryResult,
    discover_comprehensive_markets,
)
from operations.equity_discovery import (
    EquityDiscoveryResult,
    discover_us_equities,
)''',
        label="import comprehensive discovery",
    )
    content = replace_once(
        content,
        'STATE_SCHEMA = "production-context-publication-state.v4-growth"',
        'STATE_SCHEMA = "production-context-publication-state.v5-comprehensive-markets"',
        label="bump publication schema",
    )
    content = replace_once(
        content,
        "EquityDiscoveryProbe = Callable[..., EquityDiscoveryResult]\n",
        "EquityDiscoveryProbe = Callable[..., EquityDiscoveryResult]\nComprehensiveDiscoveryProbe = Callable[..., ComprehensiveMarketDiscoveryResult]\n",
        label="add comprehensive probe type",
    )
    content = replace_once(
        content,
        '''    equity_discovery_probe: EquityDiscoveryProbe | None = None,
    clock: Clock | None = None,''',
        '''    equity_discovery_probe: EquityDiscoveryProbe | None = None,
    comprehensive_discovery_probe: ComprehensiveDiscoveryProbe | None = None,
    clock: Clock | None = None,''',
        label="add comprehensive probe parameter",
    )
    content = replace_once(
        content,
        '''        discovered = discovery.instruments_for_holdings(held_symbols)
        direct_universe = load_direct_global_market_universe()
        universe = replace(
            base_universe,
            identifier=(
                f"{base_universe.identifier}+{discovery.identifier}"
                f"+{direct_universe.identifier}"
            ),
            objective=(
                base_universe.objective
                + " Daily broad U.S.-company discovery competes for exploratory capital."
            ),
            instruments=tuple((*base_universe.instruments, *discovered, *direct_universe.instruments)),
            limitations=tuple(
                dict.fromkeys(
                    (*base_universe.limitations,
                     "Individual equities enter through broad SEC/Alpaca discovery and begin with a 1% exploratory cap.",
                     *direct_universe.limitations)
                )
            ),
        )''',
        '''        discovered = discovery.instruments_for_holdings(held_symbols)
        comprehensive = (comprehensive_discovery_probe or discover_comprehensive_markets)(
            as_of=decision_as_of,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=tuple((*base_symbols, *(item.symbol for item in discovered))),
        )
        comprehensive_instruments = comprehensive.instruments_for_holdings(held_symbols)
        universe = replace(
            base_universe,
            identifier=(
                f"{base_universe.identifier}+{discovery.identifier}"
                f"+{comprehensive.identifier}"
            ),
            objective=(
                base_universe.objective
                + " Daily broad U.S.-company and comprehensive global-market discovery compete for capital."
            ),
            instruments=tuple(
                (*base_universe.instruments, *discovered, *comprehensive_instruments)
            ),
            limitations=tuple(
                dict.fromkeys(
                    (*base_universe.limitations,
                     "Individual U.S. equities enter through broad SEC/Alpaca discovery and begin with a 1% exploratory cap.",
                     "International equities, complete FX and crypto catalogs, dated futures chains, direct bonds, and long-premium defined-risk options enter through comprehensive point-in-time discovery.",
                     "Discovery can nominate instruments but cannot choose an action, size a position, construct a portfolio, authorize execution, or enable real money.")
                )
            ),
        )''',
        label="replace fixed direct universe with comprehensive discovery",
    )
    content = replace_once(
        content,
        '''                "Complete opportunity search is unavailable; a no-superior-opportunity "
                "conclusion is prohibited until broad U.S.-equity discovery completes: "''',
        '''                "Complete opportunity search is unavailable; a no-superior-opportunity "
                "conclusion is prohibited until U.S.-equity and six-lane global discovery complete: "''',
        label="update discovery failure message",
    )
    content = replace_once(
        content,
        '''                ("broad_us_equity_discovery", discovery.identifier),
                ("sec_company_master", discovery.security_master_snapshot_identifier),''',
        '''                ("broad_us_equity_discovery", discovery.identifier),
                ("sec_company_master", discovery.security_master_snapshot_identifier),
                ("comprehensive_market_discovery", comprehensive.identifier),
                ("comprehensive_market_manifest", comprehensive.manifest_fingerprint),''',
        label="add comprehensive source versions",
    )
    content = replace_once(
        content,
        '''            ("equity_discovery", "disabled" if discovery is None else discovery.policy_version),''',
        '''            ("equity_discovery", "disabled" if discovery is None else discovery.policy_version),
            ("comprehensive_market_discovery", comprehensive.policy_version),''',
        label="add comprehensive model version",
    )
    content = replace_once(
        content,
        '''        "instrument_count": len(universe.instruments),
        "opportunity_outcomes": (''',
        '''        "instrument_count": len(universe.instruments),
        "comprehensive_discovery_identifier": comprehensive.identifier,
        "comprehensive_discovery_manifest_fingerprint": comprehensive.manifest_fingerprint,
        "comprehensive_discovery_lane_counts": {
            lane.asset_class.value: {
                "catalog": lane.catalog_count,
                "deep": lane.deep_analyzed_count,
                "selected": len(lane.selected),
            }
            for lane in comprehensive.lanes
        },
        "opportunity_outcomes": (''',
        label="persist comprehensive state",
    )
    write(path, content)


def patch_render() -> None:
    path = "render.yaml"
    content = read(path)
    content = replace_once(
        content,
        '''      - key: FRED_API_KEY
        sync: false''',
        '''      - key: FRED_API_KEY
        sync: false
      - key: EODHD_API_KEY
        sync: false
      - key: DATABENTO_API_KEY
        sync: false''',
        label="add market discovery secrets",
    )
    write(path, content)


def patch_tests_and_validation() -> None:
    path = "run_release_validation.py"
    content = read(path)
    anchor = '"tests/test_equity_discovery.py",'
    if anchor in content and '"tests/test_comprehensive_market_discovery.py",' not in content:
        content = content.replace(
            anchor,
            anchor + '\n        "tests/test_comprehensive_market_discovery.py",',
            1,
        )
        write(path, content)


def main() -> None:
    patch_free_paper_pilot()
    patch_direct_global_markets()
    patch_production_evidence()
    patch_production_context()
    patch_render()
    patch_tests_and_validation()


if __name__ == "__main__":
    main()
