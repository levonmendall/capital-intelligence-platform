"""Spread OPRA validation across the chain and use retry-safe daily bars."""

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
    '''        session_date = candidates[0].session_date
        bars = self.daily_bars(
            tuple(item.raw_symbol for item in candidates),
            as_of=timestamp,
            session_date=session_date,
        )
''',
    '''        _priced_session, bars = self.latest_daily_bars(
            tuple(item.raw_symbol for item in candidates),
            as_of=timestamp,
        )
''',
    label="selection completed-session retry",
)
content = replace_once(
    content,
    '''        sample = eligible[: min(100, len(eligible))]
        bars = self.daily_bars(
            tuple(item.raw_symbol for item in sample),
            as_of=timestamp,
            session_date=sample[0].session_date,
            history_days=45,
        )
        priced = tuple(symbol for symbol, history in bars.items() if history)
''',
    '''        maximum_sample = min(240, len(eligible))
        if len(eligible) <= maximum_sample:
            sample = eligible
        else:
            indices = tuple(
                sorted(
                    {
                        round(index * (len(eligible) - 1) / (maximum_sample - 1))
                        for index in range(maximum_sample)
                    }
                )
            )
            sample = tuple(eligible[index] for index in indices)
        priced_session, bars = self.latest_daily_bars(
            tuple(item.raw_symbol for item in sample),
            as_of=timestamp,
            history_days=45,
        )
        priced = tuple(symbol for symbol, history in bars.items() if history)
''',
    label="validation chain-spanning sample",
)
content = replace_once(
    content,
    '''            "session_date": sample[0].session_date.isoformat(),
''',
    '''            "session_date": priced_session.isoformat(),
''',
    label="validation priced session lineage",
)
path.write_text(content, encoding="utf-8")

for item in (
    Path("tools/fix_databento_option_sampling.py"),
    Path(".github/workflows/fix-databento-option-sampling.yml"),
):
    item.unlink(missing_ok=True)
