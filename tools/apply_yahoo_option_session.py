"""Integrate the cookie-backed Yahoo option session and remove patch transport."""

from pathlib import Path


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


provider_path = Path("operations/provider_validation.py")
provider = provider_path.read_text(encoding="utf-8")
provider = replace_once(
    provider,
    "from providers.eodhd import EODHDProvider, EODHDProviderError\n",
    "from providers.eodhd import EODHDProvider, EODHDProviderError\n"
    "from providers.yahoo_public import YahooPublicProviderError, YahooPublicSession\n",
    label="provider validation Yahoo import",
)
provider = replace_once(
    provider,
    '''def _validate_yahoo(
    http_get: HttpGet,
    *,
    as_of: datetime,
) -> tuple[ProviderValidationCheck, ...]:''',
    '''def _validate_yahoo(
    http_get: HttpGet,
    *,
    as_of: datetime,
    yahoo_session: YahooPublicSession | None = None,
) -> tuple[ProviderValidationCheck, ...]:''',
    label="provider validation Yahoo signature",
)
option_start = provider.index(
    '    try:\n        chain = _yahoo_json(\n            http_get,\n'
    '            "https://query2.finance.yahoo.com/v7/finance/options/SPY",\n'
)
option_end = provider.index(
    "    return tuple(checks)\n\n\ndef _validate_databento",
    option_start,
)
provider_option = '''    session = yahoo_session
    if session is None and http_get is requests.get:
        session = YahooPublicSession(
            user_agent="capital-intelligence-provider-validation/1.0"
        )
    try:
        if session is None:
            chain = _yahoo_json(
                http_get,
                "https://query2.finance.yahoo.com/v7/finance/options/SPY",
            )
        else:
            chain = session.get_json(
                "https://query2.finance.yahoo.com/v7/finance/options/SPY",
                require_crumb=True,
            )
        result = chain["optionChain"]["result"]
        if not isinstance(result, list) or not result:
            raise ProviderValidationError("Yahoo option-chain result is empty")
        expirations = result[0].get("expirationDates", ())
        if not isinstance(expirations, list) or not expirations:
            raise ProviderValidationError("Yahoo option expirations are empty")
        checks.append(
            _passed(
                name="yahoo_option_chain",
                provider="YAHOO",
                required=True,
                detail=f"cookie-backed public option-chain retrieval succeeded with {len(expirations)} expirations",
                observed_at=as_of,
                source_identifier="yahoo-option-chain:SPY",
                evidence={"symbol": "SPY", "expirations": expirations[:8]},
            )
        )
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        requests.RequestException,
        ProviderValidationError,
        YahooPublicProviderError,
    ) as error:
        checks.append(
            _failed(
                name="yahoo_option_chain",
                provider="YAHOO",
                required=True,
                detail=f"{type(error).__name__}: {error}",
                observed_at=as_of,
            )
        )
'''
provider = provider[:option_start] + provider_option + provider[option_end:]
provider = replace_once(
    provider,
    '''    eodhd_provider: EODHDProvider | None = None,
    databento_provider: DatabentoProvider | None = None,
) -> ProviderValidationReport:''',
    '''    eodhd_provider: EODHDProvider | None = None,
    databento_provider: DatabentoProvider | None = None,
    yahoo_session: YahooPublicSession | None = None,
) -> ProviderValidationReport:''',
    label="live validation Yahoo dependency",
)
provider = replace_once(
    provider,
    "        *_validate_yahoo(http_get, as_of=generated_at),\n",
    "        *_validate_yahoo(\n"
    "            http_get,\n"
    "            as_of=generated_at,\n"
    "            yahoo_session=yahoo_session,\n"
    "        ),\n",
    label="live validation Yahoo invocation",
)
provider_path.write_text(provider, encoding="utf-8")


discovery_path = Path("operations/comprehensive_market_discovery.py")
discovery = discovery_path.read_text(encoding="utf-8")
discovery = replace_once(
    discovery,
    "from providers.eodhd import EODHDProvider, EODHDProviderError, build_eodhd_provider\n",
    "from providers.eodhd import EODHDProvider, EODHDProviderError, build_eodhd_provider\n"
    "from providers.yahoo_public import YahooPublicProviderError, YahooPublicSession\n",
    label="discovery Yahoo import",
)
function_start = discovery.index("def _option_catalog(\n")
function_end = discovery.index("\n\ndef default_catalog_probe(\n", function_start)
option_function = '''def _option_catalog(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
    policy: ComprehensiveMarketDiscoveryPolicy,
    http_get: Callable[..., Any] = requests.get,
    yahoo_session: YahooPublicSession | None = None,
) -> Sequence[DiscoveryCatalogRecord]:
    result: list[DiscoveryCatalogRecord] = []
    session = yahoo_session
    if session is None and http_get is requests.get:
        session = YahooPublicSession(
            user_agent="capital-intelligence-paper-research/1.0"
        )

    def option_json(
        underlying: str,
        *,
        raw_expiry: int | None = None,
    ) -> Mapping[str, Any]:
        url = f"https://query2.finance.yahoo.com/v7/finance/options/{underlying}"
        params = {} if raw_expiry is None else {"date": raw_expiry}
        if session is not None:
            return session.get_json(
                url,
                params=params,
                require_crumb=True,
            )
        response = http_get(
            url,
            params=params,
            headers={"User-Agent": "capital-intelligence-paper-research/1.0"},
            timeout=20,
        )
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise YahooPublicProviderError(f"Yahoo HTTP {status}")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise YahooPublicProviderError(
                "Yahoo returned a non-object option-chain payload"
            )
        return payload

    for underlying in config.option_underlyings:
        try:
            payload = option_json(underlying)
            chain = payload["optionChain"]["result"][0]
            expirations = tuple(int(item) for item in chain.get("expirationDates", ()))
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            requests.RequestException,
            YahooPublicProviderError,
        ):
            continue
        valid_expirations = [
            item
            for item in expirations
            if policy.option_minimum_days_to_expiry
            <= (datetime.fromtimestamp(item, tz=timezone.utc) - as_of).days
            <= policy.option_maximum_days_to_expiry
        ]
        for raw_expiry in valid_expirations[:4]:
            try:
                payload = option_json(underlying, raw_expiry=raw_expiry)
                chain = payload["optionChain"]["result"][0]
                option_sets = chain["options"][0]
                underlying_price = float(chain["quote"]["regularMarketPrice"])
            except (
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                requests.RequestException,
                YahooPublicProviderError,
            ):
                continue
            expiration = datetime.fromtimestamp(raw_expiry, tz=timezone.utc)
            for right, key in (("call", "calls"), ("put", "puts")):
                rows = option_sets.get(key, ())
                if not isinstance(rows, Sequence):
                    continue
                ranked: list[tuple[float, Mapping[str, Any]]] = []
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    strike = _number(row.get("strike"))
                    bid = _number(row.get("bid"))
                    ask = _number(row.get("ask"))
                    volume = _number(row.get("volume"))
                    open_interest = _number(row.get("openInterest"))
                    if strike <= 0.0 or ask <= 0.0 or ask < bid:
                        continue
                    moneyness = abs(strike / max(underlying_price, 1e-9) - 1.0)
                    if moneyness > 0.20:
                        continue
                    liquidity = math.log10(max(1.0, volume + open_interest))
                    spread_penalty = (ask - bid) / max(ask, 1e-9)
                    ranked.append((liquidity - 2.0 * spread_penalty - moneyness, row))
                ranked.sort(key=lambda item: item[0], reverse=True)
                for _score, row in ranked[:2]:
                    contract_symbol = str(row.get("contractSymbol", "")).strip().upper()
                    if not contract_symbol:
                        continue
                    strike = float(row["strike"])
                    result.append(
                        DiscoveryCatalogRecord(
                            symbol=contract_symbol,
                            provider_symbol=contract_symbol,
                            name=f"{underlying} {expiration.date()} {strike:g} {right}",
                            asset_class=CandidateAssetClass.OPTION,
                            economic_exposure="option_strategies",
                            venue="OPRA",
                            country_code="US",
                            currency="USD",
                            settlement_currency="USD",
                            instrument_type="option",
                            provider_kind="yahoo_option",
                            source_identifier=f"yahoo-option-chain:{underlying}:{raw_expiry}:{contract_symbol}",
                            contract_multiplier=100.0,
                            quote_spread_bps=15.0,
                            expiration_at=expiration,
                            underlying_symbol=underlying,
                            strike=strike,
                            option_right=right,
                        )
                    )
    return result
'''
discovery = discovery[:function_start] + option_function + discovery[function_end:]
discovery_path.write_text(discovery, encoding="utf-8")

for path in (
    Path("tools/apply_yahoo_option_session.py"),
    Path(".github/workflows/apply-yahoo-option-session.yml"),
):
    path.unlink(missing_ok=True)
