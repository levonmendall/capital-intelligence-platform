from __future__ import annotations

from pathlib import Path


SOURCE_PATH = Path("operations/comprehensive_market_discovery.py")
TEST_PATH = Path("tests/test_comprehensive_market_discovery.py")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


def patch_source() -> None:
    text = SOURCE_PATH.read_text()
    if "v5-terminal-market-accounting" in text:
        return

    helper = '''\n\ndef _validate_terminal_lane_accounting(\n    *,\n    asset_class: CandidateAssetClass,\n    catalog_records: Sequence[_legacy.DiscoveryCatalogRecord],\n    selected: Sequence[_legacy.DiscoveredMarketInstrument],\n    exclusions: Sequence[tuple[str, str]],\n) -> tuple[int, int]:\n    """Require a terminal selected-or-excluded disposition for every catalog record.\n\n    Comprehensive discovery certifies consideration, not forced qualification. A lane\n    may legitimately produce zero selected instruments when every catalog instrument\n    was evaluated and rejected by an unchanged policy gate. A genuinely empty catalog,\n    overlapping dispositions, unknown disposition symbols, or any unaccounted record\n    remains fail-closed.\n    """\n\n    catalog_symbols = {item.symbol for item in catalog_records}\n    if not catalog_symbols:\n        raise _legacy.ComprehensiveMarketDiscoveryError(\n            "complete discovery cannot certify an empty requested lane: "\n            + asset_class.value\n        )\n\n    selected_symbols = {item.catalog.symbol for item in selected}\n    excluded_symbols = {\n        str(symbol).strip().upper()\n        for symbol, reason in exclusions\n        if str(symbol).strip() and str(reason).strip()\n    }\n    unexpected = (selected_symbols | excluded_symbols).difference(catalog_symbols)\n    overlap = selected_symbols.intersection(excluded_symbols)\n    unaccounted = catalog_symbols.difference(selected_symbols | excluded_symbols)\n    if unexpected or overlap or unaccounted:\n        details = []\n        if unexpected:\n            details.append("unexpected=" + ",".join(sorted(unexpected)))\n        if overlap:\n            details.append("overlap=" + ",".join(sorted(overlap)))\n        if unaccounted:\n            details.append("unaccounted=" + ",".join(sorted(unaccounted)))\n        raise _legacy.ComprehensiveMarketDiscoveryError(\n            f"{asset_class.value} terminal discovery accounting is incomplete: "\n            + "; ".join(details)\n        )\n    return len(selected_symbols), len(excluded_symbols)\n'''
    text = replace_once(
        text,
        "\ndef __getattr__(name: str):\n",
        helper + "\n\ndef __getattr__(name: str):\n",
        label="terminal accounting helper",
    )
    text = replace_once(
        text,
        'version: str = "comprehensive-liquid-market-discovery.v4-complete-qualified-universe"',
        'version: str = "comprehensive-liquid-market-discovery.v5-terminal-market-accounting"',
        label="policy version",
    )
    text = replace_once(
        text,
        '''        records = tuple(\n            item\n            for item in _legacy._deduplicate(tuple(raw))\n            if item.symbol not in excluded\n            and (\n                item.expiration_at is None\n                or item.expiration_at > timestamp + timedelta(days=7)\n            )\n        )\n        state_symbols = held | tracked\n''',
        '''        catalog_records = _legacy._deduplicate(tuple(raw))\n        records = []\n        catalog_exclusions: list[tuple[str, str]] = []\n        for item in catalog_records:\n            if item.symbol in excluded:\n                catalog_exclusions.append((item.symbol, "explicit_discovery_exclusion"))\n                continue\n            if (\n                item.expiration_at is not None\n                and item.expiration_at <= timestamp + timedelta(days=7)\n            ):\n                catalog_exclusions.append(\n                    (item.symbol, "catalog_lifecycle_inside_minimum_window")\n                )\n                continue\n            records.append(item)\n        records = tuple(records)\n        state_symbols = held | tracked\n''',
        label="catalog disposition assembly",
    )
    text = replace_once(
        text,
        "        exclusions = list(plan.exclusions)\n",
        "        exclusions = [*catalog_exclusions, *plan.exclusions]\n",
        label="catalog exclusions",
    )
    text = replace_once(
        text,
        '''        source_identifiers = tuple(\n            dict.fromkeys(item.catalog.source_identifier for item in final)\n        )\n        lanes.append(\n''',
        '''        source_identifiers = tuple(\n            dict.fromkeys(item.source_identifier for item in catalog_records)\n        )\n        terminal_selected_count, terminal_excluded_count = (\n            _validate_terminal_lane_accounting(\n                asset_class=asset_class,\n                catalog_records=catalog_records,\n                selected=final,\n                exclusions=exclusions,\n            )\n        )\n        lanes.append(\n''',
        label="terminal accounting validation",
    )
    text = replace_once(
        text,
        "                catalog_count=len(records),\n",
        "                catalog_count=len(catalog_records),\n",
        label="catalog count",
    )
    text = replace_once(
        text,
        '''                "catalog": len(records),\n                "deep": len(deep_records),\n''',
        '''                "catalog": len(catalog_records),\n                "screenable": len(records),\n                "deep": len(deep_records),\n                "terminal_selected_count": terminal_selected_count,\n                "terminal_excluded_count": terminal_excluded_count,\n                "terminal_accounting_complete": True,\n''',
        label="manifest accounting",
    )
    text = replace_once(
        text,
        '''    missing = tuple(\n        lane.asset_class.value\n        for lane in lanes\n        if lane.scheduled and not lane.selected\n    )\n    if missing:\n        raise _legacy.ComprehensiveMarketDiscoveryError(\n            "complete discovery cannot certify an empty requested lane: "\n            + ", ".join(missing)\n        )\n''',
        "",
        label="forced lane qualification",
    )
    text = replace_once(
        text,
        '            "load_certified_investable_catalog",\n',
        '            "load_certified_investable_catalog",\n            "_validate_terminal_lane_accounting",\n',
        label="helper export",
    )
    SOURCE_PATH.write_text(text)


def patch_tests() -> None:
    text = TEST_PATH.read_text()
    text = replace_once(
        text,
        '''    assert "OLD" not in seen\n    assert any(item.catalog.symbol == "NEW" for item in result.selected)\n''',
        '''    assert "OLD" not in seen\n    assert any(item.catalog.symbol == "NEW" for item in result.selected)\n    future_lane = next(\n        lane for lane in result.lanes\n        if lane.asset_class is CandidateAssetClass.FUTURE\n    )\n    assert future_lane.catalog_count == 2\n    assert (\n        "OLD",\n        "catalog_lifecycle_inside_minimum_window",\n    ) in future_lane.exclusions\n    assert "source:OLD" in future_lane.source_identifiers\n''',
        label="lifecycle accounting regression",
    )
    if "test_complete_discovery_certifies_fully_rejected_lane" not in text:
        text += '''\n\ndef test_complete_discovery_certifies_fully_rejected_lane() -> None:\n    def market(records, as_of, policy):\n        result = _market(records, as_of, policy)\n        for record in records:\n            if record.asset_class is CandidateAssetClass.FX:\n                result.pop(record.symbol)\n        return result\n\n    result = discover_comprehensive_markets(\n        as_of=AS_OF,\n        catalog_probe=_catalog,\n        market_probe=market,\n    )\n\n    fx_lane = next(\n        lane for lane in result.lanes if lane.asset_class is CandidateAssetClass.FX\n    )\n    assert fx_lane.catalog_count == 1\n    assert fx_lane.selected == ()\n    assert (\n        "EURUSD",\n        "point_in_time_market_evidence_unavailable",\n    ) in fx_lane.exclusions\n    assert fx_lane.source_identifiers == ("source:EURUSD",)\n\n\ndef test_complete_discovery_certifies_lane_with_only_terminal_lifecycle_exclusions() -> None:\n    def catalog(as_of):\n        payload = dict(_catalog(as_of))\n        payload[CandidateAssetClass.FUTURE] = [\n            _record(\n                CandidateAssetClass.FUTURE,\n                "EXPIRING",\n                expiry=AS_OF + timedelta(days=2),\n            )\n        ]\n        return payload\n\n    result = discover_comprehensive_markets(\n        as_of=AS_OF,\n        catalog_probe=catalog,\n        market_probe=_market,\n    )\n\n    future_lane = next(\n        lane for lane in result.lanes\n        if lane.asset_class is CandidateAssetClass.FUTURE\n    )\n    assert future_lane.catalog_count == 1\n    assert future_lane.deep_analyzed_count == 0\n    assert future_lane.selected == ()\n    assert future_lane.exclusions == (\n        ("EXPIRING", "catalog_lifecycle_inside_minimum_window"),\n    )\n'''
    TEST_PATH.write_text(text)


if __name__ == "__main__":
    patch_source()
    patch_tests()
