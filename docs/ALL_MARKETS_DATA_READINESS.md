# All-Markets Data Readiness

## Purpose

The controlled test scope makes every classified liquid public-market family available for governed paper allocation. The version-controlled manifest at `config/all_markets_data_readiness.json` therefore declares every classified market `paper_eligible` in product scope. `other` remains prohibited because unclassified instruments cannot bypass identity and capability governance.

`paper_eligible` is a scope declaration, not a readiness claim. A market still fails closed until every required provider, data domain, instrument capability, approval, and execution control is actually ready.

The data-readiness gate is independent of asset-class approval. Data availability
alone never makes a market investable, and an asset-class approval cannot bypass
missing, unlicensed, stale, or uncertified data.

## Governing manifest

The manifest declares:

- the complete candidate-market scope;
- the portfolio reporting currency;
- every required data domain for each market;
- the providers permitted to satisfy each domain;
- minimum provider redundancy;
- required environment-variable names;
- usage-rights, point-in-time, history, provenance, service-level, storage,
  derived-analytics, and paper-simulation approvals; and
- provider-certification identifiers.

No secret values are stored in the manifest or emitted in reports.

## Current provider boundary

The repository has working official adapters for:

- FRED macroeconomic evidence, requiring `FRED_API_KEY`; and
- SEC EDGAR filings and company facts, requiring a descriptive `SEC_USER_AGENT`.

SEC EDGAR is intentionally not authoritative for historical security-master
coverage. It cannot satisfy historical identifiers, listings, delistings,
corporate actions, or survivorship-safe universe requirements by itself.

The default manifest contains disabled, fail-closed slots for external providers
that still must be selected and certified:

- global prices, quotes, liquidity, FX, commodities, benchmarks, and execution inputs;
- global reference data, corporate actions, calendars, and historical security identity;
- normalized global fundamentals and filings;
- fixed-income terms, pricing, and liquidity; and
- an independent crypto validation source.

A placeholder becomes usable only after `enabled` is true, all rights and
capability fields are approved, required environment variables are configured,
and a certification identifier is recorded when certification is required.

## Command

Evaluate the deployment without exposing credentials:

```bash
python run_data_readiness.py
```

Exit codes:

- `0` — every non-prohibited market is data ready;
- `2` — some markets are ready but the all-markets scope is incomplete;
- `3` — no usable all-markets test baseline exists; and
- `4` — manifest or execution error.

List all required configuration variable names:

```bash
python run_data_readiness.py --show-required-environment
```

Evaluate with an environment file and persist the report atomically:

```bash
python run_data_readiness.py \
  --env-file /run/secrets/data-providers.env \
  --output database/all-markets-data-readiness.json
```

The command writes one JSON document to standard output, so it can be used as a
canonical scheduled-operation preflight stage. Once the report is fully ready,
it can also generate the existing `certified_data_ready` gate payload for an
explicit governance review and append-only recording:

```bash
python run_data_readiness.py \
  --gate-certification-output certified-data-gate.json \
  --gate-identifier gate:certified-data:global-alpha.1 \
  --baseline-identifier test-baseline:global-alpha.1 \
  --process-version capital-intelligence-investment-process.v1 \
  --code-version <commit-sha> \
  --authority-identifier authority:data-governance \
  --certified-at 2026-07-27T18:00:00+00:00 \
  --effective-at 2026-07-27T18:00:00+00:00 \
  --expires-at 2026-08-26T18:00:00+00:00

python run_test_readiness_evidence.py \
  --gate-certification certified-data-gate.json
```

A blocked or partial report cannot generate a satisfied readiness gate.

## Onboarding sequence

For each external provider:

1. Review licensing, storage, backup, derived-analysis, display, retention, and
   paper-simulation rights.
2. Implement point-in-time retrieval with publication, availability, and
   retrieval timestamps.
3. Backfill sufficient history and retain revisions or vintages.
4. Reconcile identifiers, currencies, calendars, corporate actions, and prices.
5. Define freshness, completeness, and service-level policy.
6. Run deterministic provider certification.
7. Record the certification identifier and approved limitations in the manifest.
8. Configure credentials through the deployment secret manager.
9. Run `run_data_readiness.py` and retain its report as readiness evidence.
10. Keep every affected instrument blocked until its separate capability and execution approvals are active.

## Current controlled-test scope

The development manifest now places U.S. and international equities, cash, fixed income, commodities, FX, crypto, real estate, futures, options, volatility, and liquid alternatives in the intended governed paper scope. Only unclassified `other` instruments are prohibited.

This does not claim that provider onboarding is complete. The default report remains blocked until the external data supply chain is selected, licensed, configured, historically backfilled, and certified for each market. Individual instruments also require active point-in-time capability approvals before they can enter the certified universe.

Derivative markets additionally require certified contract, margin/collateral, and volatility-surface data.
