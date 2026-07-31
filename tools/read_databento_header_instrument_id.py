"""Read Databento instrument IDs from the canonical nested record header."""

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
    '''def _compact_occ_symbol(raw_symbol: str) -> str:
    compact = "".join(raw_symbol.upper().split())
    if len(compact) < 16:
        raise DatabentoOptionsError("raw OCC symbol is invalid")
    return compact


def _candidate_sessions''',
    '''def _compact_occ_symbol(raw_symbol: str) -> str:
    compact = "".join(raw_symbol.upper().split())
    if len(compact) < 16:
        raise DatabentoOptionsError("raw OCC symbol is invalid")
    return compact


def _instrument_id(row: Mapping[str, object]) -> int:
    value = row.get("instrument_id")
    if value is None:
        header = row.get("hd")
        if isinstance(header, Mapping):
            value = header.get("instrument_id")
    if isinstance(value, bool):
        raise DatabentoOptionsError("instrument_id must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise DatabentoOptionsError(
            "instrument_id is unavailable in the Databento record header"
        ) from error
    if result < 1:
        raise DatabentoOptionsError("instrument_id must be a positive integer")
    return result


def _candidate_sessions''',
    label="instrument ID header helper",
)
provider = replace_once(
    provider,
    '''                            instrument_id=int(row.get("instrument_id")),
''',
    '''                            instrument_id=_instrument_id(row),
''',
    label="definition header instrument ID",
)
provider = replace_once(
    provider,
    '''                    instrument_id = int(row.get("instrument_id"))
''',
    '''                    instrument_id = _instrument_id(row)
''',
    label="bar header instrument ID",
)
provider_path.write_text(provider, encoding="utf-8")

test_path = Path("tests/test_databento_options.py")
test = test_path.read_text(encoding="utf-8")
for instrument_id in (101, 102, 103, 104):
    test = replace_once(
        test,
        f'''                        "instrument_id": {instrument_id},
                        "asset": "SPY",
''',
        f'''                        "hd": {{"instrument_id": {instrument_id}}},
                        "asset": "SPY",
''',
        label=f"nested definition header {instrument_id}",
    )
test = replace_once(
    test,
    '''                        "instrument_id": int(instrument_id),
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
''',
    '''                        "hd": {"instrument_id": int(instrument_id)},
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
''',
    label="nested bar header",
)
test_path.write_text(test, encoding="utf-8")

for item in (
    Path("tools/read_databento_header_instrument_id.py"),
    Path(".github/workflows/read-databento-header-instrument-id.yml"),
    Path("tools/diagnose_databento_definition_keys.py"),
    Path(".github/workflows/diagnose-databento-definition-keys.yml"),
):
    item.unlink(missing_ok=True)
