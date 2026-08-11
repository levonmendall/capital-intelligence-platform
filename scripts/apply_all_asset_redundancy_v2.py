from __future__ import annotations

from pathlib import Path


def patch(path: str, old: str, new: str) -> None:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"required patch anchor missing in {path}: {old[:120]!r}")
    source.write_text(text.replace(old, new, 1), encoding="utf-8")


patch(
    "operations/comprehensive_market_discovery.py",
    "from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress\n",
    "from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress\n"
    "from operations.redundant_market_probe import default_redundant_market_probe\n"
    "from providers.redundancy_audit import begin_redundancy_cycle\n",
)
patch(
    "operations/comprehensive_market_discovery.py",
    "    resolved = policy or ComprehensiveMarketDiscoveryPolicy()\n    record_manual_cio_diagnostic_progress(\n",
    "    resolved = policy or ComprehensiveMarketDiscoveryPolicy()\n"
    "    if market_probe is None:\n"
    "        begin_redundancy_cycle(\n"
    "            f\"comprehensive-discovery:{timestamp.isoformat()}\",\n"
    "            timestamp,\n"
    "        )\n"
    "    record_manual_cio_diagnostic_progress(\n",
)
patch(
    "operations/comprehensive_market_discovery.py",
    "        features = (market_probe or _base._legacy.default_market_probe)(\n",
    "        features = (market_probe or default_redundant_market_probe)(\n",
)

patch(
    "providers/public_live_information.py",
    "from data.decision_information import (\n",
    "from providers.finra_context import (\n"
    "    FinraContextError,\n"
    "    collect_finra_fixed_income_context,\n"
    ")\n\n"
    "from data.decision_information import (\n",
)
patch(
    "providers/public_live_information.py",
    "        deduplicated = {item.content_hash: item for item in records}\n",
    "        try:\n"
    "            finra_record = collect_finra_fixed_income_context(as_of=evaluated_at)\n"
    "        except FinraContextError as error:\n"
    "            results.append(\n"
    "                PublicLiveSourceResult(\n"
    "                    source_identifier=\"finra-fixed-income-context\",\n"
    "                    source_name=\"FINRA Fixed Income Market Context\",\n"
    "                    retrieved_at=evaluated_at,\n"
    "                    configured=True,\n"
    "                    succeeded=False,\n"
    "                    record_count=0,\n"
    "                    content_hash=None,\n"
    "                    error=str(error),\n"
    "                    limitations=(\n"
    "                        \"Aggregate TRACE context only; never individual-security pricing.\",\n"
    "                    ),\n"
    "                )\n"
    "            )\n"
    "        else:\n"
    "            if finra_record is not None:\n"
    "                records.append(finra_record)\n"
    "                results.append(\n"
    "                    PublicLiveSourceResult(\n"
    "                        source_identifier=\"finra-fixed-income-context\",\n"
    "                        source_name=\"FINRA Fixed Income Market Context\",\n"
    "                        retrieved_at=evaluated_at,\n"
    "                        configured=True,\n"
    "                        succeeded=True,\n"
    "                        record_count=1,\n"
    "                        content_hash=finra_record.content_hash,\n"
    "                        error=None,\n"
    "                        limitations=(\n"
    "                            \"Aggregate TRACE context only; never individual-security pricing.\",\n"
    "                        ),\n"
    "                    )\n"
    "                )\n"
    "        deduplicated = {item.content_hash: item for item in records}\n",
)

patch(
    "cio_decision_export.py",
    "from typing import Any, Iterable, Mapping\n",
    "from typing import Any, Iterable, Mapping\n\n"
    "from providers.redundancy_audit import redundancy_audit_snapshot\n",
)
patch(
    "cio_decision_export.py",
    "        \"records\": records,\n        \"authority\": {\n",
    "        \"records\": records,\n"
    "        \"provider_redundancy_audit\": redundancy_audit_snapshot(),\n"
    "        \"authority\": {\n",
)

audit = Path("providers/provider_activation_audit.py")
text = audit.read_text(encoding="utf-8")
replacements = {
    '("option_reference", "option_history"),\n        "governed options fallback provider",': (
        '(\n            "option_reference",\n            "option_history",\n'
        '            "us_equity_history",\n            "fx_history",\n'
        '            "crypto_history",\n            "us_futures_reference",\n'
        '            "us_futures_history",\n        ),\n'
        '        "governed options fallback and capability-scoped all-asset market-history redundancy",'
    ),
    '("supplemental_quote", "us_equity_market_data", "us_option_market_data"),\n        "supplemental quote cross-check",': (
        '(\n            "supplemental_quote",\n            "us_equity_market_data",\n'
        '            "us_equity_history",\n            "us_option_market_data",\n'
        '            "active_option_chain_corroboration",\n        ),\n'
        '        "supplemental quote, equity-history failover, and active option-chain corroboration",'
    ),
    '("crypto_quote_validation",),\n        "crypto venue evidence adapter",\n        keyless=True,': (
        '("crypto_quote_validation", "crypto_history"),\n'
        '        "crypto venue quote validation and native history evidence adapter",\n'
        '        keyless=True,'
    ),
}
for old, new in replacements.items():
    count = text.count(old)
    expected = 2 if old.startswith('(\"crypto_quote_validation\"') else 1
    if count != expected:
        raise SystemExit(
            f"activation audit patch count mismatch: expected {expected}, got {count}: {old[:80]!r}"
        )
    text = text.replace(old, new)
old_finra = '''    ProviderActivationSpec(
        "finra",
        ("fixed_income_market_structure", "trace"),
        None,
        ("FINRA_CLIENT_ID", "FINRA_CLIENT_SECRET"),
        note=(
            "FINRA credentials and live fixed-income probing are wired, but FINRA market "
            "context is intentionally reported unrouted until a governed CIO evidence "
            "consumer is added; aggregate TRACE data is not substituted for bond prices."
        ),
    ),
'''
new_finra = '''    ProviderActivationSpec(
        "finra",
        ("fixed_income_market_structure", "trace", "specialist_environment_context"),
        "governed public-live fixed-income specialist/environment context",
        ("FINRA_CLIENT_ID", "FINRA_CLIENT_SECRET"),
        note=(
            "FINRA aggregate TRACE context is routed to specialist/environment evidence only; "
            "it cannot satisfy individual-bond identity, price, history, valuation, or execution."
        ),
    ),
'''
if old_finra not in text:
    raise SystemExit("FINRA activation audit anchor missing")
audit.write_text(text.replace(old_finra, new_finra, 1), encoding="utf-8")
