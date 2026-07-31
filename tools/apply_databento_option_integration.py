"""Replace rate-limited Yahoo option chains with authenticated Databento OPRA."""

from pathlib import Path


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


# Add a holiday-safe latest-bar helper to the new provider.
options_path = Path("providers/databento_options.py")
options = options_path.read_text(encoding="utf-8")
anchor = "    def select_contracts(\n"
if options.count(anchor) != 1:
    raise RuntimeError("Databento option select_contracts anchor is invalid")
latest_bars = '''    def latest_daily_bars(
        self,
        raw_symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> tuple[date, Mapping[str, tuple[DatabentoOptionBar, ...]]]:
        """Return the newest completed-session bars, retrying exchange holidays."""

        timestamp = _aware(as_of, field_name="as_of")
        failures: list[str] = []
        for session_date in _candidate_sessions(timestamp):
            try:
                bars = self.daily_bars(
                    raw_symbols,
                    as_of=timestamp,
                    session_date=session_date,
                    history_days=history_days,
                )
            except DatabentoOptionsError as error:
                failures.append(str(error))
                continue
            if bars:
                return session_date, bars
            failures.append(f"no priced bars through {session_date.isoformat()}")
        detail = failures[-1] if failures else "no completed session was available"
        raise DatabentoOptionsError(
            f"Databento OPRA daily bars are unavailable: {detail}"
        )

'''
options = options.replace(anchor, latest_bars + anchor, 1)
options_path.write_text(options, encoding="utf-8")


# Replace the discovery option lane and market evidence path.
discovery_path = Path("operations/comprehensive_market_discovery.py")
discovery = discovery_path.read_text(encoding="utf-8")
discovery = replace_once(
    discovery,
    "from providers.eodhd import EODHDProvider, EODHDProviderError, build_eodhd_provider\n"
    "from providers.yahoo_public import YahooPublicProviderError, YahooPublicSession\n",
    "from providers.databento_options import (\n"
    "    DATABENTO_OPRA_DATASET,\n"
    "    DatabentoOptionsError,\n"
    "    DatabentoOptionsProvider,\n"
    ")\n"
    "from providers.eodhd import EODHDProvider, EODHDProviderError, build_eodhd_provider\n",
    label="discovery provider imports",
)
option_start = discovery.index("def _option_catalog(\n")
option_end = discovery.index("\n\ndef default_catalog_probe(\n", option_start)
option_function = '''def _option_catalog(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
    policy: ComprehensiveMarketDiscoveryPolicy,
    http_get: Callable[..., Any] = requests.get,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> Sequence[DiscoveryCatalogRecord]:
    provider = databento_options_provider or DatabentoOptionsProvider()
    if not provider.configured:
        raise ComprehensiveMarketDiscoveryError(
            "Databento OPRA credentials are required for defined-risk option discovery"
        )
    result: list[DiscoveryCatalogRecord] = []
    for underlying in config.option_underlyings:
        underlying_record = DiscoveryCatalogRecord(
            symbol=underlying,
            provider_symbol=underlying,
            name=underlying,
            asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
            economic_exposure="us_equity",
            venue="US",
            country_code="US",
            currency="USD",
            settlement_currency="USD",
            instrument_type="common_stock",
            provider_kind="yahoo",
            source_identifier=f"yahoo-chart:{underlying}",
        )
        rows = _yahoo_rows(
            underlying_record,
            as_of=as_of,
            history_days=15,
            http_get=http_get,
        )
        if not rows:
            continue
        underlying_price = float(rows[-1]["c"])
        try:
            selections = provider.select_contracts(
                underlying,
                underlying_price=underlying_price,
                as_of=as_of,
                minimum_days_to_expiry=policy.option_minimum_days_to_expiry,
                maximum_days_to_expiry=policy.option_maximum_days_to_expiry,
            )
        except (DatabentoOptionsError, OSError, TypeError, ValueError):
            continue
        for selection in selections:
            definition = selection.definition
            bar = selection.bar
            result.append(
                DiscoveryCatalogRecord(
                    symbol=definition.symbol,
                    provider_symbol=definition.raw_symbol,
                    name=(
                        f"{definition.underlying} {definition.expiration_at.date()} "
                        f"{definition.strike:g} {definition.option_right}"
                    ),
                    asset_class=CandidateAssetClass.OPTION,
                    economic_exposure="option_strategies",
                    venue="OPRA",
                    country_code="US",
                    currency="USD",
                    settlement_currency="USD",
                    instrument_type="option",
                    provider_kind="databento",
                    provider_dataset=DATABENTO_OPRA_DATASET,
                    provider_stype_in="raw_symbol",
                    source_identifier=(
                        "databento-opra-definition:"
                        f"{definition.session_date.isoformat()}:"
                        f"{definition.symbol}:bar:{bar.observed_at.isoformat()}"
                    ),
                    contract_multiplier=definition.contract_multiplier,
                    quote_spread_bps=15.0,
                    expiration_at=definition.expiration_at,
                    underlying_symbol=definition.underlying,
                    strike=definition.strike,
                    option_right=definition.option_right,
                )
            )
    return result
'''
discovery = discovery[:option_start] + option_function + discovery[option_end:]
discovery = replace_once(
    discovery,
    '''    eodhd_provider: EODHDProvider | None = None,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:''',
    '''    eodhd_provider: EODHDProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:''',
    label="catalog probe Databento dependency",
)
discovery = replace_once(
    discovery,
    '''            policy=resolved_policy,
        )
    )
    return result''',
    '''            policy=resolved_policy,
            databento_options_provider=databento_options_provider,
        )
    )
    return result''',
    label="catalog probe option invocation",
)
discovery = replace_once(
    discovery,
    '''    http_get: Callable[..., Any] = requests.get,
    eodhd_provider: EODHDProvider | None = None,
) -> Mapping[str, DiscoveryMarketFeatures]:''',
    '''    http_get: Callable[..., Any] = requests.get,
    eodhd_provider: EODHDProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> Mapping[str, DiscoveryMarketFeatures]:''',
    label="market probe Databento dependency",
)
discovery = replace_once(
    discovery,
    '''    provider = eodhd_provider or build_eodhd_provider()
    result: dict[str, DiscoveryMarketFeatures] = {}
    for record in records:
        if record.asset_class is CandidateAssetClass.OPTION and record.underlying_symbol:''',
    '''    provider = eodhd_provider or build_eodhd_provider()
    options_provider = databento_options_provider or DatabentoOptionsProvider()
    option_records = tuple(
        item for item in records if item.asset_class is CandidateAssetClass.OPTION
    )
    option_histories: Mapping[str, tuple[object, ...]] = {}
    if option_records and options_provider.configured:
        try:
            _option_session, option_histories = options_provider.latest_daily_bars(
                tuple(item.provider_symbol for item in option_records),
                as_of=timestamp,
                history_days=min(policy.history_days, 365),
            )
        except (DatabentoOptionsError, OSError, TypeError, ValueError):
            option_histories = {}
    result: dict[str, DiscoveryMarketFeatures] = {}
    for record in records:
        option_evidence: tuple[str, ...] = ()
        if record.asset_class is CandidateAssetClass.OPTION and record.underlying_symbol:''',
    label="market probe option prefetch",
)
discovery = replace_once(
    discovery,
    '''            option_rows = _yahoo_rows(
                record,
                as_of=timestamp,
                history_days=min(policy.history_days, 365),
                http_get=http_get,
            )
            option_price = float(option_rows[-1]["c"]) if option_rows else 0.0
        elif record.provider_kind in {"yahoo", "yahoo_option"}:''',
    '''            option_rows = option_histories.get(record.provider_symbol.upper(), ())
            option_price = float(option_rows[-1].close) if option_rows else 0.0
            if option_rows:
                option_material = [
                    {
                        "t": item.observed_at.isoformat(),
                        "c": item.close,
                        "v": item.volume,
                    }
                    for item in option_rows
                ]
                option_evidence = (
                    f"databento-opra-bars:{record.symbol}:{_hash(option_material)}",
                )
        elif record.provider_kind == "yahoo":''',
    label="market probe option pricing",
)
discovery = replace_once(
    discovery,
    '''            evidence_identifiers=(
                record.source_identifier,
                f"discovery-bars:{record.symbol}:{_hash(material)}",
            ),''',
    '''            evidence_identifiers=(
                record.source_identifier,
                f"discovery-bars:{record.symbol}:{_hash(material)}",
                *option_evidence,
            ),''',
    label="market probe option lineage",
)
discovery_path.write_text(discovery, encoding="utf-8")


# Make authenticated Databento OPRA a required live-provider proof.
validation_path = Path("operations/provider_validation.py")
validation = validation_path.read_text(encoding="utf-8")
validation = replace_once(
    validation,
    "from providers.eodhd import EODHDProvider, EODHDProviderError\n"
    "from providers.yahoo_public import YahooPublicProviderError, YahooPublicSession\n",
    "from providers.databento_options import (\n"
    "    DatabentoOptionsError,\n"
    "    DatabentoOptionsProvider,\n"
    ")\n"
    "from providers.eodhd import EODHDProvider, EODHDProviderError\n",
    label="validation provider imports",
)
yahoo_start = validation.index("def _validate_yahoo(\n")
yahoo_end = validation.index("\n\ndef _validate_databento(\n", yahoo_start)
yahoo_function = '''def _validate_yahoo(
    http_get: HttpGet,
    *,
    as_of: datetime,
) -> tuple[ProviderValidationCheck, ...]:
    start = int((as_of - timedelta(days=10)).timestamp())
    end = int(as_of.timestamp())
    try:
        chart = _yahoo_json(
            http_get,
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
            params={
                "period1": start,
                "period2": end,
                "interval": "1d",
                "events": "history",
            },
        )
        result = chart["chart"]["result"]
        if not isinstance(result, list) or not result:
            raise ProviderValidationError("Yahoo chart result is empty")
        timestamps = result[0].get("timestamp", ())
        quote = result[0].get("indicators", {}).get("quote", ())[0]
        closes = tuple(item for item in quote.get("close", ()) if item is not None)
        if not isinstance(timestamps, list) or not timestamps or not closes:
            raise ProviderValidationError("Yahoo chart observations are empty")
        return (
            _passed(
                name="yahoo_chart_evidence",
                provider="YAHOO",
                required=True,
                detail=f"public chart retrieval succeeded with {len(timestamps)} observations",
                observed_at=as_of,
                source_identifier="yahoo-chart:SPY",
                evidence={
                    "symbol": "SPY",
                    "timestamps": timestamps[-5:],
                    "latest_close": closes[-1],
                },
            ),
        )
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        requests.RequestException,
        ProviderValidationError,
    ) as error:
        return (
            _failed(
                name="yahoo_chart_evidence",
                provider="YAHOO",
                required=True,
                detail=f"{type(error).__name__}: {error}",
                observed_at=as_of,
            ),
        )
'''
validation = validation[:yahoo_start] + yahoo_function + validation[yahoo_end:]
databento_start = validation.index("def _validate_databento(\n")
databento_end = validation.index("\n\ndef validate_live_providers(\n", databento_start)
databento_function = '''def _validate_databento(
    provider: DatabentoProvider,
    options_provider: DatabentoOptionsProvider,
    *,
    as_of: datetime,
) -> tuple[ProviderValidationCheck, ...]:
    checks: list[ProviderValidationCheck] = []
    if not provider.configured:
        checks.append(
            _failed(
                name="databento_account_entitlement",
                provider="DATABENTO",
                required=True,
                detail="required Databento API key is not configured",
                observed_at=as_of,
            )
        )
    else:
        try:
            snapshot = provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.ACCOUNT_ENTITLEMENT,
                    provider_symbol="ACCOUNT",
                    as_of=as_of,
                    limit=1_000,
                )
            )
            count = _payload_count(snapshot.payload)
            if count < 1:
                raise DatabentoProviderError(
                    "provider returned an empty dataset entitlement list"
                )
            checks.append(
                _passed(
                    name="databento_account_entitlement",
                    provider="DATABENTO",
                    required=True,
                    detail=(
                        "authenticated dataset discovery succeeded with "
                        f"{count} records"
                    ),
                    observed_at=snapshot.retrieved_at,
                    source_identifier=snapshot.provider_record_id,
                    evidence={
                        "content_hash": snapshot.content_hash,
                        "provider": snapshot.provider,
                        "source_version": snapshot.source_version,
                        "count": count,
                    },
                )
            )
        except (DatabentoProviderError, OSError, TypeError, ValueError) as error:
            checks.append(
                _failed(
                    name="databento_account_entitlement",
                    provider="DATABENTO",
                    required=True,
                    detail=f"{type(error).__name__}: {error}",
                    observed_at=as_of,
                )
            )
    if not options_provider.configured:
        detail = "required Databento OPRA credentials are not configured"
        checks.extend(
            (
                _failed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
                _failed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
            )
        )
        return tuple(checks)
    try:
        proof = options_provider.validate_access(as_of=as_of)
        checks.extend(
            (
                _passed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=(
                        "completed-session OPRA definition retrieval succeeded with "
                        f"{proof['definition_count']} contracts"
                    ),
                    observed_at=as_of,
                    source_identifier=(
                        f"databento-opra-definitions:SPY:{proof['session_date']}"
                    ),
                    evidence={
                        "dataset": proof["dataset"],
                        "session_date": proof["session_date"],
                        "definition_count": proof["definition_count"],
                        "eligible_definition_count": proof[
                            "eligible_definition_count"
                        ],
                    },
                ),
                _passed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=(
                        "completed-session OPRA daily-bar retrieval succeeded with "
                        f"{proof['priced_sample_count']} priced sample contracts"
                    ),
                    observed_at=as_of,
                    source_identifier=(
                        f"databento-opra-bars:SPY:{proof['session_date']}"
                    ),
                    evidence={
                        "dataset": proof["dataset"],
                        "session_date": proof["session_date"],
                        "priced_sample_count": proof["priced_sample_count"],
                        "sample_symbols": proof["sample_symbols"],
                    },
                ),
            )
        )
    except (DatabentoOptionsError, OSError, TypeError, ValueError) as error:
        detail = f"{type(error).__name__}: {error}"
        checks.extend(
            (
                _failed(
                    name="databento_opra_definitions",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
                _failed(
                    name="databento_opra_daily_bars",
                    provider="DATABENTO",
                    required=True,
                    detail=detail,
                    observed_at=as_of,
                ),
            )
        )
    return tuple(checks)
'''
validation = validation[:databento_start] + databento_function + validation[databento_end:]
validation = replace_once(
    validation,
    '''    eodhd_provider: EODHDProvider | None = None,
    databento_provider: DatabentoProvider | None = None,
    yahoo_session: YahooPublicSession | None = None,
) -> ProviderValidationReport:''',
    '''    eodhd_provider: EODHDProvider | None = None,
    databento_provider: DatabentoProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> ProviderValidationReport:''',
    label="validation Databento option dependency",
)
validation = replace_once(
    validation,
    '''    else:
        databento = databento_provider
    checks = (
        *_validate_eodhd(eodhd, as_of=generated_at),
        *_validate_yahoo(
            http_get,
            as_of=generated_at,
            yahoo_session=yahoo_session,
        ),
        _validate_databento(databento, as_of=generated_at),
    )''',
    '''    else:
        databento = databento_provider
    databento_options = (
        databento_options_provider or DatabentoOptionsProvider()
    )
    checks = (
        *_validate_eodhd(eodhd, as_of=generated_at),
        *_validate_yahoo(http_get, as_of=generated_at),
        *_validate_databento(
            databento,
            databento_options,
            as_of=generated_at,
        ),
    )''',
    label="validation check assembly",
)
validation = validation.replace(
    "retrieve current public Yahoo market/option evidence",
    "retrieve current Yahoo chart evidence and completed-session Databento OPRA evidence",
    1,
)
validation_path.write_text(validation, encoding="utf-8")


# Keep documentation aligned with the actual provider path and licensing boundary.
docs_path = Path("docs/COMPREHENSIVE_MARKET_DISCOVERY.md")
docs = docs_path.read_text(encoding="utf-8")
docs = docs.replace(
    "Yahoo chart and option-chain endpoints provide public paper-research evidence where configured. Dated futures use explicit exchange contract symbols and can be upgraded to Databento-native evidence without changing the discovery contract.",
    "Yahoo chart endpoints provide public underlying-history evidence. Defined-risk options use authenticated Databento `OPRA.PILLAR` definitions and daily OHLCV from the latest completed session, avoiding any claim of unlicensed live OPRA access. Dated futures use explicit exchange contract symbols and can be upgraded to Databento-native evidence without changing the discovery contract.",
)
docs_path.write_text(docs, encoding="utf-8")


for path in (
    Path("tools/apply_databento_option_integration.py"),
    Path(".github/workflows/apply-databento-option-integration.yml"),
):
    path.unlink(missing_ok=True)
