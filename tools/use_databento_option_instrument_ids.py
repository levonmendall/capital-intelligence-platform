"""Use Databento instrument IDs for bounded OPRA daily-bar retrieval."""

from pathlib import Path


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


def replace_between(content: str, start: str, end: str, replacement: str, *, label: str) -> str:
    start_index = content.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return content[:start_index] + replacement + content[end_index:]


provider_path = Path("providers/databento_options.py")
provider = provider_path.read_text(encoding="utf-8")
provider = replace_between(
    provider,
    "@dataclass(frozen=True, slots=True)\nclass DatabentoOptionDefinition:\n",
    "\n\n@dataclass(frozen=True, slots=True)\nclass DatabentoOptionBar:\n",
    '''@dataclass(frozen=True, slots=True)
class DatabentoOptionDefinition:
    symbol: str
    raw_symbol: str
    instrument_id: int
    underlying: str
    option_right: str
    expiration_at: datetime
    strike: float
    contract_multiplier: float
    session_date: date

    def __post_init__(self) -> None:
        symbol = _text(self.symbol, field_name="symbol").upper()
        raw_symbol = _text(self.raw_symbol, field_name="raw_symbol").upper()
        underlying = _text(self.underlying, field_name="underlying").upper()
        instrument_id = self.instrument_id
        if (
            isinstance(instrument_id, bool)
            or not isinstance(instrument_id, int)
            or instrument_id < 1
        ):
            raise ValueError("instrument_id must be a positive integer")
        if self.option_right not in {"call", "put"}:
            raise ValueError("option_right must be call or put")
        expiration = _aware(self.expiration_at, field_name="expiration_at")
        strike = _number(self.strike, field_name="strike")
        multiplier = _number(self.contract_multiplier, field_name="contract_multiplier")
        if strike <= 0.0 or multiplier <= 0.0:
            raise ValueError("strike and contract_multiplier must be positive")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "raw_symbol", raw_symbol)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "underlying", underlying)
        object.__setattr__(self, "expiration_at", expiration)
        object.__setattr__(self, "strike", strike)
        object.__setattr__(self, "contract_multiplier", multiplier)
''',
    label="option definition instrument ID",
)
provider = replace_once(
    provider,
    '''                            raw_symbol=raw_symbol,
                            underlying=row_underlying,
''',
    '''                            raw_symbol=raw_symbol,
                            instrument_id=int(row.get("instrument_id")),
                            underlying=row_underlying,
''',
    label="definition instrument ID parsing",
)
provider = replace_between(
    provider,
    "    def daily_bars(\n",
    "    def select_contracts(\n",
    '''    def daily_bars(
        self,
        instruments: Sequence[DatabentoOptionDefinition | tuple[int, str]],
        *,
        as_of: datetime,
        session_date: date,
        history_days: int = 45,
    ) -> Mapping[str, tuple[DatabentoOptionBar, ...]]:
        """Return completed-session bars using provider-native instrument IDs."""

        timestamp = _aware(as_of, field_name="as_of")
        instrument_lookup: dict[int, str] = {}
        for item in instruments:
            if isinstance(item, DatabentoOptionDefinition):
                instrument_id = item.instrument_id
                raw_symbol = item.raw_symbol
            else:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise TypeError(
                        "instruments must contain definitions or (instrument_id, raw_symbol) tuples"
                    )
                instrument_id, raw_symbol = item
            if (
                isinstance(instrument_id, bool)
                or not isinstance(instrument_id, int)
                or instrument_id < 1
            ):
                raise ValueError("instrument_id must be a positive integer")
            normalized_symbol = _text(raw_symbol, field_name="raw_symbol").upper()
            instrument_lookup.setdefault(instrument_id, normalized_symbol)
        instrument_ids = tuple(instrument_lookup)
        if not instrument_ids:
            return {}
        if history_days < 1 or history_days > 400:
            raise ValueError("history_days must be between 1 and 400")
        end_date = session_date + timedelta(days=1)
        start_date = end_date - timedelta(days=history_days)
        grouped: dict[str, list[DatabentoOptionBar]] = {
            raw_symbol: [] for raw_symbol in instrument_lookup.values()
        }
        batch_size = 20
        for offset in range(0, len(instrument_ids), batch_size):
            batch = instrument_ids[offset : offset + batch_size]
            rows = self._records(
                data={
                    "dataset": DATABENTO_OPRA_DATASET,
                    "schema": "ohlcv-1d",
                    "symbols": ",".join(str(item) for item in batch),
                    "stype_in": "instrument_id",
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "encoding": "json",
                    "pretty_px": "true",
                    "pretty_ts": "true",
                    "limit": max(1_000, len(batch) * history_days),
                }
            )
            for row in rows:
                try:
                    instrument_id = int(row.get("instrument_id"))
                    symbol = instrument_lookup.get(instrument_id)
                    if symbol is None:
                        continue
                    observed = _timestamp(
                        row.get("pretty_ts_event", row.get("ts_event")),
                        field_name="option bar timestamp",
                    )
                    if observed > timestamp:
                        continue
                    grouped[symbol].append(
                        DatabentoOptionBar(
                            raw_symbol=symbol,
                            observed_at=observed,
                            close=_number(
                                row.get("pretty_close", row.get("close")),
                                field_name="close",
                            ),
                            volume=max(
                                0.0,
                                _number(row.get("volume", 0.0), field_name="volume"),
                            ),
                        )
                    )
                except (DatabentoOptionsError, TypeError, ValueError):
                    continue
        return {
            symbol: tuple(sorted(values, key=lambda item: item.observed_at))
            for symbol, values in grouped.items()
            if values
        }

    def latest_daily_bars(
        self,
        instruments: Sequence[DatabentoOptionDefinition | tuple[int, str]],
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
                    instruments,
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

''',
    label="instrument-ID bar retrieval",
)
provider = replace_once(
    provider,
    '''        _priced_session, bars = self.latest_daily_bars(
            tuple(item.raw_symbol for item in candidates),
            as_of=timestamp,
        )
''',
    '''        _priced_session, bars = self.latest_daily_bars(
            tuple(candidates),
            as_of=timestamp,
        )
''',
    label="selection instrument-ID bars",
)
provider_path.write_text(provider, encoding="utf-8")

operation_path = Path("operations/comprehensive_market_discovery.py")
operation = operation_path.read_text(encoding="utf-8")
operation = replace_once(
    operation,
    '''    provider_dataset: str | None = None
    provider_stype_in: str | None = None
''',
    '''    provider_dataset: str | None = None
    provider_stype_in: str | None = None
    provider_instrument_id: int | None = None
''',
    label="catalog provider instrument ID field",
)
operation = replace_once(
    operation,
    '''        if self.expiration_at is not None:
            object.__setattr__(
                self,
                "expiration_at",
                _aware(self.expiration_at, field_name="expiration_at"),
            )
''',
    '''        if self.expiration_at is not None:
            object.__setattr__(
                self,
                "expiration_at",
                _aware(self.expiration_at, field_name="expiration_at"),
            )
        if self.provider_instrument_id is not None:
            if (
                isinstance(self.provider_instrument_id, bool)
                or not isinstance(self.provider_instrument_id, int)
                or self.provider_instrument_id < 1
            ):
                raise ValueError("provider_instrument_id must be a positive integer")
''',
    label="catalog provider instrument ID validation",
)
operation = replace_once(
    operation,
    '''                    provider_dataset=DATABENTO_OPRA_DATASET,
                    provider_stype_in="raw_symbol",
                    source_identifier=(
''',
    '''                    provider_dataset=DATABENTO_OPRA_DATASET,
                    provider_stype_in="instrument_id",
                    provider_instrument_id=definition.instrument_id,
                    source_identifier=(
''',
    label="option catalog instrument ID lineage",
)
operation = replace_once(
    operation,
    '''            _option_session, option_histories = options_provider.latest_daily_bars(
                tuple(item.provider_symbol for item in option_records),
                as_of=timestamp,
                history_days=min(policy.history_days, 365),
            )
''',
    '''            option_instruments = tuple(
                (item.provider_instrument_id, item.provider_symbol)
                for item in option_records
                if item.provider_instrument_id is not None
            )
            if len(option_instruments) != len(option_records):
                raise DatabentoOptionsError(
                    "option records are missing provider instrument IDs"
                )
            _option_session, option_histories = options_provider.latest_daily_bars(
                option_instruments,
                as_of=timestamp,
                history_days=min(policy.history_days, 365),
            )
''',
    label="option market probe instrument IDs",
)
operation_path.write_text(operation, encoding="utf-8")

test_path = Path("tests/test_databento_options.py")
test = test_path.read_text(encoding="utf-8")
for index, raw_symbol in enumerate(
    (
        "SPY   260918C00620000",
        "SPY   260918P00620000",
        "SPY   261218C00625000",
        "SPY   261218P00625000",
    ),
    start=101,
):
    test = replace_once(
        test,
        f'''                        "raw_symbol": "{raw_symbol}",
                        "asset": "SPY",
''',
        f'''                        "raw_symbol": "{raw_symbol}",
                        "instrument_id": {index},
                        "asset": "SPY",
''',
        label=f"definition fixture instrument ID {index}",
    )
test = replace_between(
    test,
    '''        if data["schema"] == "ohlcv-1d":
''',
    '''        raise AssertionError(data)
''',
    '''        if data["schema"] == "ohlcv-1d":
            records = []
            for instrument_id in data["symbols"].split(","):
                records.append(
                    {
                        "instrument_id": int(instrument_id),
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
                        "pretty_close": "12.500000000",
                        "volume": "25",
                    }
                )
            return _Response(records=records)
''',
    label="instrument-ID bar fixture",
)
test = replace_once(
    test,
    '''    assert all(
        call[1]["data"]["stype_in"] == "raw_symbol"
        and call[1]["data"]["map_symbols"] == "true"
        and "stype_out" not in call[1]["data"]
        for call in post.calls
        if call[1]["data"]["schema"] == "ohlcv-1d"
    )
''',
    '''    assert all(
        call[1]["data"]["stype_in"] == "instrument_id"
        and "map_symbols" not in call[1]["data"]
        and "stype_out" not in call[1]["data"]
        for call in post.calls
        if call[1]["data"]["schema"] == "ohlcv-1d"
    )
''',
    label="instrument-ID request assertion",
)
test = replace_once(
    test,
    '''    symbols = tuple(
        f"SPY   260918C{600000 + index:08d}"
        for index in range(45)
    )

    bars = provider.daily_bars(
        symbols,
''',
    '''    instruments = tuple(
        (
            1_000 + index,
            f"SPY   260918C{600000 + index:08d}",
        )
        for index in range(45)
    )

    bars = provider.daily_bars(
        instruments,
''',
    label="batch test instrument tuples",
)
test = replace_once(
    test,
    '''    assert sum(len(batch) for batch in requests) == len(symbols)
    assert set(bars) == set(symbols)
''',
    '''    assert sum(len(batch) for batch in requests) == len(instruments)
    assert set(bars) == {raw_symbol for _instrument_id, raw_symbol in instruments}
''',
    label="batch test expectations",
)
test_path.write_text(test, encoding="utf-8")

for item in (
    Path("tools/use_databento_option_instrument_ids.py"),
    Path(".github/workflows/use-databento-option-instrument-ids.yml"),
    Path("tools/diagnose_databento_opra_json.py"),
    Path(".github/workflows/diagnose-databento-opra-json.yml"),
):
    item.unlink(missing_ok=True)
