"""Correct explicit credential handling and fail-closed option pricing."""

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
    '''        resolved = (
            api_key
            or os.getenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY")
            or os.getenv("DATABENTO_API_KEY")
            or ""
        ).strip()
''',
    '''        if api_key is None:
            resolved = (
                os.getenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY")
                or os.getenv("DATABENTO_API_KEY")
                or ""
            ).strip()
        else:
            resolved = str(api_key).strip()
''',
    label="explicit Databento key semantics",
)
provider_path.write_text(provider, encoding="utf-8")


discovery_path = Path("operations/comprehensive_market_discovery.py")
discovery = discovery_path.read_text(encoding="utf-8")
discovery = replace_once(
    discovery,
    '''        if len(rows) < policy.minimum_history_bars:
            continue
        closes = [float(item["c"]) for item in rows]
''',
    '''        if len(rows) < policy.minimum_history_bars:
            continue
        if record.asset_class is CandidateAssetClass.OPTION and option_price <= 0.0:
            continue
        closes = [float(item["c"]) for item in rows]
''',
    label="option price fail closed",
)
discovery = replace_once(
    discovery,
    '''        result[record.symbol] = DiscoveryMarketFeatures(
            price=price,
            observed_at=rows[-1]["t"],
''',
    '''        observed_at = (
            option_rows[-1].observed_at
            if record.asset_class is CandidateAssetClass.OPTION and option_rows
            else rows[-1]["t"]
        )
        result[record.symbol] = DiscoveryMarketFeatures(
            price=price,
            observed_at=observed_at,
''',
    label="option observation timestamp",
)
discovery_path.write_text(discovery, encoding="utf-8")


for path in (
    Path("tools/fix_databento_option_contracts.py"),
    Path(".github/workflows/fix-databento-option-contracts.yml"),
):
    path.unlink(missing_ok=True)
