"""Normalize Databento OPRA symbols and parse display-price fields."""

from pathlib import Path


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


provider_path = Path("providers/databento_options.py")
provider = provider_path.read_text(encoding="utf-8")
provider = replace_once(
    provider,
    '''        symbols = tuple(
            dict.fromkeys(
                _text(item, field_name="raw_symbol").upper()
                for item in raw_symbols
            )
        )
        if not symbols:
            return {}
''',
    '''        symbol_lookup: dict[str, str] = {}
        for item in raw_symbols:
            raw_symbol = _text(item, field_name="raw_symbol").upper()
            symbol_lookup.setdefault(_compact_occ_symbol(raw_symbol), raw_symbol)
        symbols = tuple(symbol_lookup.values())
        if not symbols:
            return {}
''',
    label="canonical OCC input lookup",
)
provider = replace_once(
    provider,
    '''                    "stype_in": "raw_symbol",
                    "start": start_date.isoformat(),
''',
    '''                    "stype_in": "raw_symbol",
                    "stype_out": "raw_symbol",
                    "start": start_date.isoformat(),
''',
    label="raw-symbol output mapping",
)
provider = replace_once(
    provider,
    '''                    symbol = _text(row.get("symbol"), field_name="symbol").upper()
                    if symbol not in grouped:
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
                            close=_number(row.get("close"), field_name="close"),
                            volume=max(
                                0.0,
                                _number(row.get("volume", 0.0), field_name="volume"),
                            ),
                        )
                    )
''',
    '''                    provider_symbol = _text(
                        row.get("symbol"),
                        field_name="symbol",
                    ).upper()
                    symbol = symbol_lookup.get(_compact_occ_symbol(provider_symbol))
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
''',
    label="normalized OPRA row mapping",
)
provider_path.write_text(provider, encoding="utf-8")

test_path = Path("tests/test_databento_options.py")
test = test_path.read_text(encoding="utf-8")
test = replace_once(
    test,
    '''                        "symbol": symbol,
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
                        "close": "12.500000000",
''',
    '''                        "symbol": "".join(symbol.split()),
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
                        "pretty_close": "12.500000000",
''',
    label="Databento normalized JSON fixture",
)
test = replace_once(
    test,
    '''    symbols = tuple(f"SPY_OPT_{index:03d}" for index in range(45))
''',
    '''    symbols = tuple(
        f"SPY   260918C{600000 + index:08d}"
        for index in range(45)
    )
''',
    label="valid OCC batching symbols",
)
test_path.write_text(test, encoding="utf-8")

for item in (
    Path("tools/fix_databento_opra_row_mapping.py"),
    Path(".github/workflows/fix-databento-opra-row-mapping.yml"),
):
    item.unlink(missing_ok=True)
