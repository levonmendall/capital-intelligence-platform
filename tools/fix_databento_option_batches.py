"""Batch OPRA daily-bar requests and bound the chain validation sample."""

from pathlib import Path


def replace_once(content: str, old: str, new: str, *, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return content.replace(old, new, 1)


path = Path("providers/databento_options.py")
content = path.read_text(encoding="utf-8")
content = replace_once(
    content,
    '''        rows = self._records(
            data={
                "dataset": DATABENTO_OPRA_DATASET,
                "schema": "ohlcv-1d",
                "symbols": ",".join(symbols),
                "stype_in": "raw_symbol",
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "encoding": "json",
                "pretty_px": "true",
                "pretty_ts": "true",
                "map_symbols": "true",
                "limit": max(1_000, len(symbols) * history_days),
            }
        )
        grouped: dict[str, list[DatabentoOptionBar]] = {item: [] for item in symbols}
        for row in rows:
            try:
                symbol = _text(row.get("symbol"), field_name="symbol").upper()
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
                        volume=max(0.0, _number(row.get("volume", 0.0), field_name="volume")),
                    )
                )
            except (DatabentoOptionsError, TypeError, ValueError):
                continue
''',
    '''        grouped: dict[str, list[DatabentoOptionBar]] = {item: [] for item in symbols}
        batch_size = 20
        for offset in range(0, len(symbols), batch_size):
            batch = symbols[offset : offset + batch_size]
            rows = self._records(
                data={
                    "dataset": DATABENTO_OPRA_DATASET,
                    "schema": "ohlcv-1d",
                    "symbols": ",".join(batch),
                    "stype_in": "raw_symbol",
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "encoding": "json",
                    "pretty_px": "true",
                    "pretty_ts": "true",
                    "map_symbols": "true",
                    "limit": max(1_000, len(batch) * history_days),
                }
            )
            for row in rows:
                try:
                    symbol = _text(row.get("symbol"), field_name="symbol").upper()
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
                except (DatabentoOptionsError, TypeError, ValueError):
                    continue
''',
    label="bounded OPRA daily-bar batches",
)
content = replace_once(
    content,
    '''        maximum_sample = min(240, len(eligible))
''',
    '''        maximum_sample = min(80, len(eligible))
''',
    label="bounded validation sample",
)
path.write_text(content, encoding="utf-8")

for item in (
    Path("tools/fix_databento_option_batches.py"),
    Path(".github/workflows/fix-databento-option-batches.yml"),
):
    item.unlink(missing_ok=True)
