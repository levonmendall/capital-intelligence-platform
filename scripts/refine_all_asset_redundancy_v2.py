from __future__ import annotations

from pathlib import Path


def patch(path: str, old: str, new: str, *, count: int = 1) -> None:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual < count:
        raise SystemExit(
            f"required patch anchor missing in {path}: expected>={count}, got={actual}: {old[:100]!r}"
        )
    source.write_text(text.replace(old, new, count), encoding="utf-8")


# Predeclare every candidate so an unattempted configured fallback is still visible.
patch(
    "providers/redundant_market_history.py",
    "        attempted: list[str] = []\n        failures: list[tuple[str, str]] = []\n        for index, candidate in enumerate(candidates):\n            key = candidate.key\n            if ledger is not None:\n                ledger.declare(\n                    key,\n                    configured=candidate.configured,\n                    authenticated=candidate.authenticated,\n                    routed=True,\n                    certified_for_evidence_role=candidate.certified_for_evidence_role,\n                )\n",
    "        attempted: list[str] = []\n"
    "        failures: list[tuple[str, str]] = []\n"
    "        if ledger is not None:\n"
    "            for candidate in candidates:\n"
    "                ledger.declare(\n"
    "                    candidate.key,\n"
    "                    configured=candidate.configured,\n"
    "                    authenticated=candidate.authenticated,\n"
    "                    routed=True,\n"
    "                    certified_for_evidence_role=candidate.certified_for_evidence_role,\n"
    "                )\n"
    "        for index, candidate in enumerate(candidates):\n"
    "            key = candidate.key\n",
)

# Candidate credentials are configured, not authenticated, until a successful call.
probe = Path("operations/redundant_market_probe.py")
text = probe.read_text(encoding="utf-8")
text = text.replace(
    "def add(provider, capability, dataset, symbol, loader, *, configured=True, authenticated=True, fixed_income=False, exact=True):",
    "def add(provider, capability, dataset, symbol, loader, *, configured=True, authenticated=False, fixed_income=False, exact=True):",
)
for provider_expression in (
    "authenticated=tradier.configured",
    "authenticated=massive.configured",
    "authenticated=twelve.configured",
    "authenticated=eodhd_provider.configured",
    "authenticated=databento_futures.configured",
):
    text = text.replace(provider_expression, "authenticated=False")
# Public/keyless providers have no secret authentication step to prove.
text = text.replace(
    'add("yahoo", "us_equity_history", "chart", record.provider_symbol,',
    'add("yahoo", "us_equity_history", "chart", record.provider_symbol,',
)
text = text.replace(
    'lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get))',
    'lambda: _legacy._yahoo_rows(record, as_of=as_of, history_days=history_days, http_get=http_get), authenticated=True)',
)
# The blanket Yahoo replacement may affect every exact Yahoo candidate by design.
text = text.replace(
    'lambda: coinbase.daily_history(coinbase_symbol, as_of=as_of, history_days=history_days))',
    'lambda: coinbase.daily_history(coinbase_symbol, as_of=as_of, history_days=history_days), authenticated=True)',
)
text = text.replace(
    'lambda: kraken.daily_history(kraken_symbol, as_of=as_of, history_days=history_days))',
    'lambda: kraken.daily_history(kraken_symbol, as_of=as_of, history_days=history_days), authenticated=True)',
)
# Tradier chain auth is not declared proven until a successful chain response.
text = text.replace(
    "ledger.declare(key, configured=tradier.configured, authenticated=tradier.configured, routed=True, certified_for_evidence_role=True)",
    "ledger.declare(key, configured=tradier.configured, authenticated=False, routed=True, certified_for_evidence_role=True)",
)

primary_helper = '''\n\ndef _mark_existing_result_usage(\n    records: Sequence[_legacy.DiscoveryCatalogRecord],\n    features: Mapping[str, _legacy.DiscoveryMarketFeatures],\n) -> None:\n    \"\"\"Record provider-native first-pass successes in the cycle audit.\"\"\"\n\n    ledger = current_redundancy_ledger()\n    if ledger is None:\n        return\n    for record in records:\n        feature = features.get(record.symbol)\n        if feature is None:\n            continue\n        sources = tuple(feature.evidence_identifiers)\n        if record.asset_class is CandidateAssetClass.OPTION:\n            providers = tuple(\n                provider\n                for provider in (\"databento\", \"massive\")\n                if any(provider in source.lower() for source in sources)\n            )\n            if not providers and record.provider_kind in {\"databento\", \"massive\"}:\n                providers = (record.provider_kind,)\n            for provider in providers:\n                dataset = \"OPRA.PILLAR\" if provider == \"databento\" else \"OPRA\"\n                key = ProviderCapabilityKey(provider, \"option_evidence\", dataset)\n                ledger.declare(\n                    key,\n                    configured=True,\n                    authenticated=True,\n                    routed=True,\n                    certified_for_evidence_role=True,\n                )\n                ledger.used(\n                    key,\n                    source_identifiers=tuple(\n                        source for source in sources if provider in source.lower()\n                    ),\n                    failed_over=provider == \"massive\",\n                )\n            continue\n        provider = record.provider_kind.strip().lower()\n        capability = {\n            CandidateAssetClass.US_EQUITY: \"us_equity_history\",\n            CandidateAssetClass.US_ETF: \"us_equity_history\",\n            CandidateAssetClass.INTERNATIONAL_EQUITY: \"international_equity_history\",\n            CandidateAssetClass.FX: \"fx_history\",\n            CandidateAssetClass.CRYPTO: \"crypto_history\",\n            CandidateAssetClass.FUTURE: \"futures_history\",\n            CandidateAssetClass.FIXED_INCOME: \"fixed_income_exact_security_history\",\n        }.get(record.asset_class)\n        if not provider or capability is None:\n            continue\n        dataset = record.provider_dataset or {\n            \"alpaca\": \"IEX\",\n            \"eodhd\": \"eodhd-history\",\n            \"yahoo\": \"chart\",\n            \"databento\": \"GLBX.MDP3\",\n            \"massive\": \"market-aggs\",\n        }.get(provider, \"provider-native\")\n        key = ProviderCapabilityKey(provider, capability, dataset)\n        ledger.declare(\n            key,\n            configured=True,\n            authenticated=True,\n            routed=True,\n            certified_for_evidence_role=True,\n        )\n        ledger.used(key, source_identifiers=sources, failed_over=False)\n'''
anchor = "\ndef default_redundant_market_probe(\n"
if anchor not in text:
    raise SystemExit("redundant market probe helper anchor missing")
text = text.replace(anchor, primary_helper + anchor, 1)
text = text.replace(
    "    result = dict(_legacy.default_market_probe(records, timestamp, policy, http_get=http_get))\n",
    "    result = dict(_legacy.default_market_probe(records, timestamp, policy, http_get=http_get))\n"
    "    _mark_existing_result_usage(records, result)\n",
    1,
)
probe.write_text(text, encoding="utf-8")

# FINRA context participates in the same cycle ledger, but remains context only.
finra = Path("providers/finra_context.py")
text = finra.read_text(encoding="utf-8")
text = text.replace(
    "from providers.finra_fixed_income import (\n",
    "from providers.redundancy_audit import (\n"
    "    ProviderCapabilityKey,\n"
    "    current_redundancy_ledger,\n"
    ")\n"
    "from providers.finra_fixed_income import (\n",
    1,
)
text = text.replace(
    "    build_finra_fixed_income_provider,\n",
    "    FinraFixedIncomeError,\n    build_finra_fixed_income_provider,\n",
    1,
)
old = """    provider = build_finra_fixed_income_provider()\n    if provider is None:\n        return None\n    cutoff = as_of.astimezone(timezone.utc)\n    token, _token_type, _expires = provider._access_token()  # noqa: SLF001 -- same bounded OAuth adapter\n"""
new = """    key = ProviderCapabilityKey(\n        \"finra\",\n        \"fixed_income_market_context\",\n        FINRA_TREASURY_DAILY_AGGREGATES,\n    )\n    ledger = current_redundancy_ledger()\n    try:\n        provider = build_finra_fixed_income_provider()\n    except (FinraFixedIncomeError, TypeError, ValueError) as error:\n        if ledger is not None:\n            ledger.declare(\n                key,\n                configured=True,\n                authenticated=False,\n                routed=True,\n                certified_for_evidence_role=True,\n            )\n            ledger.failed(key, \"authentication_or_entitlement\")\n        raise FinraContextError(\"FINRA OAuth credentials are invalid\") from error\n    if provider is None:\n        if ledger is not None:\n            ledger.declare(\n                key,\n                configured=False,\n                authenticated=False,\n                routed=True,\n                certified_for_evidence_role=True,\n            )\n        return None\n    cutoff = as_of.astimezone(timezone.utc)\n    if ledger is not None:\n        ledger.declare(\n            key,\n            configured=True,\n            authenticated=False,\n            routed=True,\n            certified_for_evidence_role=True,\n        )\n        ledger.attempted(key)\n    try:\n        token, _token_type, _expires = provider._access_token()  # noqa: SLF001 -- same bounded OAuth adapter\n    except FinraFixedIncomeError as error:\n        if ledger is not None:\n            ledger.failed(key, \"authentication_or_entitlement\")\n        raise FinraContextError(\"FINRA OAuth authentication failed\") from error\n    if ledger is not None:\n        ledger.authenticated(key)\n"""
if old not in text:
    raise SystemExit("FINRA context provider anchor missing")
text = text.replace(old, new, 1)
text = text.replace(
    "    if not 200 <= status < 300:\n        raise FinraContextError(\n            f\"FINRA fixed-income context returned HTTP {status or 'unknown'}\"\n        )\n",
    "    if not 200 <= status < 300:\n"
    "        if ledger is not None:\n"
    "            ledger.failed(\n"
    "                key,\n"
    "                \"authentication_or_entitlement\" if status in {401, 403} else \"provider_evidence_unavailable\",\n"
    "            )\n"
    "        raise FinraContextError(\n"
    "            f\"FINRA fixed-income context returned HTTP {status or 'unknown'}\"\n"
    "        )\n",
    1,
)
return_anchor = """    return DecisionInformationRecord(\n        identifier=f\"finra-context:treasury:{latest_date.isoformat()}:{digest[:16]}\",\n"""
if return_anchor not in text:
    raise SystemExit("FINRA context return anchor missing")
text = text.replace(
    return_anchor,
    """    source_identifier = (\n        f\"{FINRA_TREASURY_DAILY_AGGREGATES}:{latest_date.isoformat()}\"\n    )\n    if ledger is not None:\n        ledger.used(\n            key,\n            source_identifiers=(source_identifier,),\n            failed_over=False,\n        )\n    return DecisionInformationRecord(\n        identifier=f\"finra-context:treasury:{latest_date.isoformat()}:{digest[:16]}\",\n""",
    1,
)
text = text.replace(
    "                f\"{FINRA_TREASURY_DAILY_AGGREGATES}:{latest_date.isoformat()}\"\n            ),",
    "                source_identifier\n            ),",
    1,
)
finra.write_text(text, encoding="utf-8")

# Treasury Fiscal Data remains reference-only, but its cycle use is observable.
treasury = Path("providers/treasury_fiscal_data.py")
text = treasury.read_text(encoding="utf-8")
text = text.replace(
    "import requests\n",
    "import requests\n\n"
    "from providers.redundancy_audit import (\n"
    "    ProviderCapabilityKey,\n"
    "    current_redundancy_ledger,\n"
    ")\n",
    1,
)
start = """        as_of_date = as_of.astimezone(timezone.utc).date()\n        fields = \",\".join(\n"""
replacement = """        as_of_date = as_of.astimezone(timezone.utc).date()\n        audit_key = ProviderCapabilityKey(\n            \"treasury_fiscal_data\",\n            \"treasury_security_reference\",\n            \"auctions_query\",\n        )\n        ledger = current_redundancy_ledger()\n        if ledger is not None:\n            ledger.declare(\n                audit_key,\n                configured=True,\n                authenticated=True,\n                routed=True,\n                certified_for_evidence_role=True,\n            )\n            ledger.attempted(audit_key)\n        fields = \",\".join(\n"""
if start not in text:
    raise SystemExit("Treasury audit start anchor missing")
text = text.replace(start, replacement, 1)
end = """        return tuple(\n            sorted(\n                latest_by_cusip.values(),\n                key=lambda item: (item.maturity_date, item.cusip),\n            )\n        )\n"""
new_end = """        result = tuple(\n            sorted(\n                latest_by_cusip.values(),\n                key=lambda item: (item.maturity_date, item.cusip),\n            )\n        )\n        if ledger is not None:\n            ledger.used(\n                audit_key,\n                source_identifiers=tuple(\n                    item.evidence_identifier for item in result[:25]\n                ),\n                failed_over=False,\n            )\n        return result\n"""
if end not in text:
    raise SystemExit("Treasury audit end anchor missing")
text = text.replace(end, new_end, 1)
treasury.write_text(text, encoding="utf-8")
