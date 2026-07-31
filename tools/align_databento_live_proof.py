"""Align Databento OPRA live validation with the production near-money selector."""

from pathlib import Path


def replace_between(content: str, start: str, end: str, replacement: str, *, label: str) -> str:
    start_index = content.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return content[:start_index] + replacement + content[end_index:]


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


options_path = Path("providers/databento_options.py")
options = options_path.read_text(encoding="utf-8")
options = replace_between(
    options,
    "    def validate_access(self, *, as_of: datetime) -> dict[str, object]:\n",
    "\n\n__all__ = [",
    '''    def validate_access(
        self,
        *,
        as_of: datetime,
        underlying_price: float,
    ) -> dict[str, object]:
        """Prove the same completed-session, near-money OPRA path used in production."""

        timestamp = _aware(as_of, field_name="as_of")
        price = _number(underlying_price, field_name="underlying_price")
        if price <= 0.0:
            raise ValueError("underlying_price must be positive")
        definitions = self.definitions("SPY", as_of=timestamp)
        eligible = tuple(
            item
            for item in definitions
            if 30 <= (item.expiration_at - timestamp).days <= 365
            and abs(item.strike / price - 1.0) <= 0.20
        )
        if not eligible:
            raise DatabentoOptionsError(
                "SPY OPRA definitions contain no eligible near-money expirations"
            )
        selections = self.select_contracts(
            "SPY",
            underlying_price=price,
            as_of=timestamp,
            minimum_days_to_expiry=30,
            maximum_days_to_expiry=365,
            maximum_expirations=3,
            candidates_per_bucket=12,
        )
        if not selections:
            raise DatabentoOptionsError(
                "SPY OPRA near-money contracts contain no completed-session prices"
            )
        priced_session = max(item.bar.observed_at.date() for item in selections)
        return {
            "dataset": DATABENTO_OPRA_DATASET,
            "session_date": priced_session.isoformat(),
            "definition_count": len(definitions),
            "eligible_definition_count": len(eligible),
            "priced_sample_count": len(selections),
            "sample_symbols": tuple(
                item.definition.symbol for item in selections[:5]
            ),
        }
''',
    label="Databento production-aligned validation",
)
options_path.write_text(options, encoding="utf-8")

validation_path = Path("operations/provider_validation.py")
validation = validation_path.read_text(encoding="utf-8")
validation = replace_between(
    validation,
    "def _validate_yahoo(\n",
    "\n\ndef _validate_databento(\n",
    '''def _validate_yahoo(
    http_get: HttpGet,
    *,
    as_of: datetime,
) -> tuple[tuple[ProviderValidationCheck, ...], float | None]:
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
        closes = tuple(float(item) for item in quote.get("close", ()) if item is not None)
        if not isinstance(timestamps, list) or not timestamps or not closes:
            raise ProviderValidationError("Yahoo chart observations are empty")
        latest_close = closes[-1]
        if latest_close <= 0.0:
            raise ProviderValidationError("Yahoo latest SPY close is not positive")
        return (
            (
                _passed(
                    name="yahoo_chart_evidence",
                    provider="YAHOO",
                    required=True,
                    detail=(
                        "public chart retrieval succeeded with "
                        f"{len(timestamps)} observations"
                    ),
                    observed_at=as_of,
                    source_identifier="yahoo-chart:SPY",
                    evidence={
                        "symbol": "SPY",
                        "timestamps": timestamps[-5:],
                        "latest_close": latest_close,
                    },
                ),
            ),
            latest_close,
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
            (
                _failed(
                    name="yahoo_chart_evidence",
                    provider="YAHOO",
                    required=True,
                    detail=f"{type(error).__name__}: {error}",
                    observed_at=as_of,
                ),
            ),
            None,
        )
''',
    label="Yahoo price-bearing validation",
)
validation = replace_between(
    validation,
    "def _validate_databento(\n",
    "\n\ndef validate_live_providers(\n",
    '''def _validate_databento(
    provider: DatabentoProvider,
    options_provider: DatabentoOptionsProvider,
    *,
    as_of: datetime,
    underlying_price: float | None,
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
    if underlying_price is None or underlying_price <= 0.0:
        detail = "current SPY reference price is unavailable for near-money OPRA validation"
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
        proof = options_provider.validate_access(
            as_of=as_of,
            underlying_price=underlying_price,
        )
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
                        "production-aligned near-money OPRA retrieval succeeded with "
                        f"{proof['priced_sample_count']} priced contracts"
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
''',
    label="production-aligned Databento validation",
)
validation = replace_once(
    validation,
    '''    checks = (
        *_validate_eodhd(eodhd, as_of=generated_at),
        *_validate_yahoo(http_get, as_of=generated_at),
        *_validate_databento(
            databento,
            databento_options,
            as_of=generated_at,
        ),
    )
''',
    '''    yahoo_checks, spy_reference_price = _validate_yahoo(
        http_get,
        as_of=generated_at,
    )
    checks = (
        *_validate_eodhd(eodhd, as_of=generated_at),
        *yahoo_checks,
        *_validate_databento(
            databento,
            databento_options,
            as_of=generated_at,
            underlying_price=spy_reference_price,
        ),
    )
''',
    label="provider validation orchestration",
)
validation_path.write_text(validation, encoding="utf-8")

provider_test_path = Path("tests/test_provider_validation.py")
provider_test = provider_test_path.read_text(encoding="utf-8")
provider_test = replace_once(
    provider_test,
    '''    def validate_access(self, *, as_of):
        assert as_of == NOW
''',
    '''    def validate_access(self, *, as_of, underlying_price):
        assert as_of == NOW
        assert underlying_price == 610.0
''',
    label="provider validation test double",
)
provider_test_path.write_text(provider_test, encoding="utf-8")

options_test_path = Path("tests/test_databento_options.py")
options_test = options_test_path.read_text(encoding="utf-8")
options_test = replace_once(
    options_test,
    '''    result = provider.validate_access(as_of=AS_OF)
''',
    '''    result = provider.validate_access(
        as_of=AS_OF,
        underlying_price=620.0,
    )
''',
    label="Databento access test reference price",
)
options_test_path.write_text(options_test, encoding="utf-8")

for item in (
    Path("tools/align_databento_live_proof.py"),
    Path(".github/workflows/align-databento-live-proof.yml"),
):
    item.unlink(missing_ok=True)
