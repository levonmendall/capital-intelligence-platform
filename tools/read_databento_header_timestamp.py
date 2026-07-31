"""Read Databento event timestamps from the canonical nested record header."""

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
    '''    if result < 1:
        raise DatabentoOptionsError("instrument_id must be a positive integer")
    return result


def _candidate_sessions''',
    '''    if result < 1:
        raise DatabentoOptionsError("instrument_id must be a positive integer")
    return result


def _event_timestamp(row: Mapping[str, object]) -> datetime:
    value = row.get("pretty_ts_event", row.get("ts_event"))
    if value is None:
        header = row.get("hd")
        if isinstance(header, Mapping):
            value = header.get("pretty_ts_event", header.get("ts_event"))
    return _timestamp(value, field_name="option bar timestamp")


def _candidate_sessions''',
    label="nested event timestamp helper",
)
provider = replace_once(
    provider,
    '''                    observed = _timestamp(
                        row.get("pretty_ts_event", row.get("ts_event")),
                        field_name="option bar timestamp",
                    )
''',
    '''                    observed = _event_timestamp(row)
''',
    label="bar timestamp header parsing",
)
provider_path.write_text(provider, encoding="utf-8")

test_path = Path("tests/test_databento_options.py")
test = test_path.read_text(encoding="utf-8")
test = replace_once(
    test,
    '''                        "hd": {"instrument_id": int(instrument_id)},
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
                        "pretty_close": "12.500000000",
''',
    '''                        "hd": {
                            "instrument_id": int(instrument_id),
                            "ts_event": "2026-07-30T13:30:00.000000000Z",
                        },
                        "close": "12.500000000",
''',
    label="nested bar timestamp fixture",
)
test_path.write_text(test, encoding="utf-8")

for item in (
    Path("tools/read_databento_header_timestamp.py"),
    Path(".github/workflows/read-databento-header-timestamp.yml"),
    Path("tools/diagnose_databento_option_identifiers.py"),
    Path(".github/workflows/diagnose-databento-option-identifiers.yml"),
):
    item.unlink(missing_ok=True)
