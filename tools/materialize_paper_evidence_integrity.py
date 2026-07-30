from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}, found {source.count(old)}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, *, expected: int) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if source.count(old) != expected:
        raise RuntimeError(
            f"expected {expected} matches in {path}, found {source.count(old)}"
        )
    target.write_text(source.replace(old, new), encoding="utf-8")


def patch_evidence() -> None:
    replace_once(
        "production_paper_evidence.py",
        "from __future__ import annotations\n\nfrom dataclasses import dataclass",
        "from __future__ import annotations\n\nimport hashlib\nimport json\nfrom dataclasses import dataclass",
    )
    replace_once(
        "production_paper_evidence.py",
        "_HISTORY_DAYS = 365 * 5 + 10",
        "_HISTORY_DAYS = 365 * 10 + 20",
    )
    replace_all(
        "production_paper_evidence.py",
        '"FEDFUNDS"',
        '"DFF"',
        expected=2,
    )
    helper = '''\n\ndef _evidence_digest(value: object) -> str:\n    return hashlib.sha256(\n        json.dumps(\n            value,\n            sort_keys=True,\n            separators=(",", ":"),\n            allow_nan=False,\n        ).encode("utf-8")\n    ).hexdigest()\n'''
    replace_once(
        "production_paper_evidence.py",
        "\n\ndef _default_probe(\n",
        helper + "\n\ndef _default_probe(\n",
    )
    replace_once(
        "production_paper_evidence.py",
        '''    as_of: datetime,\n    cash_expected_return: float,\n) -> ListedWrapperFeatures:\n''',
        '''    as_of: datetime,\n    cash_expected_return: float,\n    maximum_quote_age_minutes: int,\n) -> ListedWrapperFeatures:\n''',
    )
    old_quote = '''    quote_price: float | None = None\n    if isinstance(quote, Mapping):\n        quote_time = _timestamp(quote.get("t"), field_name=f"{symbol} quote timestamp")\n        if quote_time > as_of + timedelta(seconds=5):\n            raise ProductionPaperEvidenceError(f"{symbol} quote is future-known")\n        bid = quote.get("bp")\n        ask = quote.get("ap")\n        if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):\n            if float(bid) > 0.0 and float(ask) >= float(bid):\n                quote_price = (float(bid) + float(ask)) / 2.0\n    current_price = closes[-1] if quote_price is None else quote_price\n'''
    new_quote = '''    if not isinstance(quote, Mapping):\n        raise ProductionPaperEvidenceError(f"current quote is unavailable for {symbol}")\n    quote_time = _timestamp(quote.get("t"), field_name=f"{symbol} quote timestamp")\n    if quote_time > as_of + timedelta(seconds=5):\n        raise ProductionPaperEvidenceError(f"{symbol} quote is future-known")\n    quote_age = as_of - quote_time\n    if quote_age > timedelta(minutes=maximum_quote_age_minutes):\n        raise ProductionPaperEvidenceError(\n            f"{symbol} quote exceeds the {maximum_quote_age_minutes}-minute evidence limit"\n        )\n    bid = quote.get("bp")\n    ask = quote.get("ap")\n    quote_price: float | None = None\n    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):\n        if float(bid) > 0.0 and float(ask) >= float(bid):\n            quote_price = (float(bid) + float(ask)) / 2.0\n    current_price = closes[-1] if quote_price is None else quote_price\n'''
    replace_once("production_paper_evidence.py", old_quote, new_quote)
    old_evidence = '''    evidence = tuple(\n        f"alpaca-iex-bar:{symbol}:{item['t'].isoformat()}"\n        for item in rows[-12:]\n    )\n    return ListedWrapperFeatures(\n        symbol=symbol,\n        as_of=as_of,\n        current_price=round(current_price, 8),\n        latest_observed_at=rows[-1]["t"],\n'''
    new_evidence = '''    bar_material = [\n        {\n            "t": item["t"].isoformat(),\n            "c": round(float(item["c"]), 12),\n            "v": round(float(item["v"]), 4),\n        }\n        for item in rows\n    ]\n    quote_material = {\n        "t": quote_time.isoformat(),\n        "bp": None if bid is None else float(bid),\n        "ap": None if ask is None else float(ask),\n    }\n    evidence = (\n        (\n            f"alpaca-iex-bars:{symbol}:{rows[0]['t'].isoformat()}:"\n            f"{rows[-1]['t'].isoformat()}:{len(rows)}:{_evidence_digest(bar_material)}"\n        ),\n        f"alpaca-iex-quote:{symbol}:{quote_time.isoformat()}:{_evidence_digest(quote_material)}",\n    )\n    return ListedWrapperFeatures(\n        symbol=symbol,\n        as_of=as_of,\n        current_price=round(current_price, 8),\n        latest_observed_at=max(rows[-1]["t"], quote_time),\n'''
    replace_once("production_paper_evidence.py", old_evidence, new_evidence)
    old_macro = '''    for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF"):\n        date, number = _macro_value(raw, series)\n        values[series] = number\n        identifiers.append(f"fred:{series}:{date}")\n'''
    new_macro = '''    for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF"):\n        date, number = _macro_value(raw, series)\n        try:\n            observation_date = datetime.fromisoformat(date).date()\n        except ValueError as error:\n            raise ProductionPaperEvidenceError(\n                f"FRED {series} observation date is invalid"\n            ) from error\n        if observation_date > as_of.date():\n            raise ProductionPaperEvidenceError(\n                f"FRED {series} observation is future-known"\n            )\n        if (as_of.date() - observation_date).days > 10:\n            raise ProductionPaperEvidenceError(\n                f"FRED {series} observation is stale"\n            )\n        values[series] = number\n        identifiers.append(f"fred:{series}:{date}")\n'''
    replace_once("production_paper_evidence.py", old_macro, new_macro)
    replace_all(
        "production_paper_evidence.py",
        '("FRED_MACRO", as_of.date().isoformat()),',
        '''(\n                "FRED_MACRO",\n                hashlib.sha256(\n                    "|".join(macro_identifiers).encode("utf-8")\n                ).hexdigest(),\n            ),''',
        expected=2,
    )
    replace_once(
        "production_paper_evidence.py",
        '''                as_of=as_of,\n                cash_expected_return=cash_expected_return,\n            )\n''',
        '''                as_of=as_of,\n                cash_expected_return=cash_expected_return,\n                maximum_quote_age_minutes=universe.maximum_quote_age_minutes,\n            )\n''',
    )


def patch_publication() -> None:
    replace_once(
        "production_context_publication_governed.py",
        '("fred_macro", "DGS10,T10Y2Y,VIXCLS,FEDFUNDS"),',
        '("fred_macro", "DGS10,T10Y2Y,VIXCLS,DFF"),',
    )


def patch_tests() -> None:
    replace_all(
        "tests/test_production_context_publication_runtime.py",
        '"FEDFUNDS"',
        '"DFF"',
        expected=1,
    )
    first_assertion = '''    assert result.candidate_count == 15\n    assert result.exclusion_count == 0\n\n    cycle = _executor(settings, tmp_path).run(as_of=decision_time)\n'''
    expanded = '''    assert result.candidate_count == 15\n    assert result.exclusion_count == 0\n    context = _provider(settings, tmp_path).load_context(as_of=decision_time)\n    assert any(\n        item.startswith("alpaca-iex-bars:VTI:")\n        for item in context.manifest.evidence_identifiers\n    )\n    assert any(\n        item.startswith("alpaca-iex-quote:VTI:")\n        for item in context.manifest.evidence_identifiers\n    )\n\n    cycle = _executor(settings, tmp_path).run(as_of=decision_time)\n'''
    replace_once(
        "tests/test_production_context_publication_runtime.py",
        first_assertion,
        expanded,
    )
    insertion = '''\n\ndef test_future_macro_observation_blocks_publication(tmp_path) -> None:\n    settings = _settings(tmp_path)\n    scheduled_for = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)\n    decision_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)\n    _bootstrap_cash_portfolio(\n        settings,\n        as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),\n    )\n    payload = _evidence(decision_time)\n    payload["macro"]["DGS10"]["date"] = "2026-07-30"\n\n    result = prepare_production_context_for_cycle(\n        settings=settings,\n        scheduled_for=scheduled_for,\n        readiness_probe=lambda _universe: _readiness(decision_time),\n        cash_probe=lambda: SimpleNamespace(date="2026-07-28", value=4.25),\n        evidence_probe=lambda _universe, _as_of: payload,\n        clock=lambda: decision_time,\n    )\n\n    assert result.state == "blocked"\n    assert "future-known" in result.detail\n'''
    replace_once(
        "tests/test_production_context_publication_runtime.py",
        "\ndef test_completed_publication_is_reused_without_new_provider_calls(tmp_path) -> None:\n",
        insertion + "\n\ndef test_completed_publication_is_reused_without_new_provider_calls(tmp_path) -> None:\n",
    )


def main() -> None:
    patch_evidence()
    patch_publication()
    patch_tests()


if __name__ == "__main__":
    main()
