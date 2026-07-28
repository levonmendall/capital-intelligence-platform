# External Data Provider Stack

## Purpose

This integration creates the first concrete external-data stack for the controlled all-markets paper test. It does not declare the data licensed, complete, point-in-time safe, or certified merely because an endpoint responds.

The stack has three layers:

1. official evidence from FRED and SEC EDGAR;
2. broad multi-asset end-of-day evidence from EODHD; and
3. independent spot-crypto top-of-book validation from Coinbase Exchange and Kraken.

A separate institutional reference-data provider is still required before the global security master can become authoritative. A separate execution-grade quote source may also be required for non-crypto paper execution because EOD bars are not bid/ask liquidity.

## EODHD adapter

`providers.eodhd.EODHDProvider` implements both:

- `CanonicalMarketDataProvider` for daily OHLCV bars and historical dividends or splits; and
- `ProviderDatasetProvider` for immutable provider-native datasets.

Supported raw datasets are:

- account entitlement and API-access evidence;
- exchange directory;
- active and delisted symbol directories;
- global fundamentals;
- market history for equities, funds, FX, crypto, and supported bonds;
- dividends and splits;
- commodity history; and
- fixed-income history or terms exposed by the selected product entitlement.

The adapter intentionally rejects quote, trade, funding-rate, and open-interest queries. It never converts an EOD close into a bid/ask quote.

### Required configuration

```text
CAPITAL_INTELLIGENCE_EODHD_API_TOKEN
CAPITAL_INTELLIGENCE_EODHD_BINDINGS
```

The binding document maps a stable internal instrument ID to an EODHD symbol, venue, and currency. It contains no API key.

Probe account access without exposing the token:

```bash
python run_eodhd_provider.py probe --as-of 2026-07-27T23:59:59+00:00
```

Retrieve a raw fundamentals snapshot:

```bash
python run_eodhd_provider.py dataset \
  --type fundamentals \
  --provider-symbol AAPL.US \
  --as-of 2026-07-27T23:59:59+00:00
```

Retrieve canonical daily bars after creating instrument bindings:

```bash
python run_eodhd_provider.py \
  --bindings /run/secrets/eodhd-instrument-bindings.json \
  market \
  --instrument-id instrument:us-equity:aapl \
  --type bar \
  --start-at 2025-01-01T00:00:00+00:00 \
  --as-of 2026-07-27T23:59:59+00:00
```

## Independent crypto venue adapters

`providers.crypto_venues` supplies two separate canonical quote providers:

- `CoinbaseExchangeProvider`; and
- `KrakenSpotProvider`.

Both adapters are read-only and use public market-data endpoints. They have no account, order, custody, withdrawal, or live-execution authority.

Required configuration:

```text
CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS
```

The same internal crypto instrument must be mapped independently to each venue's product identifier. A two-provider requirement remains in the all-markets readiness manifest so one venue cannot certify the entire crypto market.

## Immutable historical backfills

`operations.provider_backfill.ProviderBackfillRunner` executes a versioned `provider-backfill-plan.v1` document. It:

- splits each requested history into bounded date windows;
- keeps the data interval separate from the knowledge cutoff;
- fetches provider-native snapshots through `ProviderDatasetProvider`;
- stores one JSON artifact per provider, task, symbol, and date window;
- hashes every artifact;
- reuses identical reruns; and
- refuses to overwrite different bytes at the same immutable path.

Run the example plan:

```bash
python run_provider_backfill.py \
  --plan config/eodhd_backfill_plan.example.json \
  --output-directory data/provider-backfills/eodhd-initial
```

The example plan is illustrative. Production plans must be reviewed for the licensed retention period, universe, date range, rate limits, and provider entitlement.

## Certification sequence

Endpoint access is only the first step. The controlled test must retain the following order:

1. purchase or approve the provider subscription;
2. document permitted storage, backup, derived analytics, display, and paper-simulation use;
3. inject secrets through the deployment secret manager;
4. run entitlement and coverage probes;
5. execute historical backfills;
6. reconcile record counts, identifiers, currencies, calendars, actions, prices, and timestamps;
7. run deterministic provider-certification scenarios;
8. record an approved, expiring certification identifier;
9. append an expiring provider activation record with the reviewed capability facts; and
10. rerun `python run_data_readiness.py` with the activation registry.

No adapter may set its own licensing or certification flags to true.

## Known boundaries

This first stack does not by itself provide:

- a survivorship-safe historical security master;
- complete merger, spinoff, symbol-change, venue-change, and delisting history;
- consolidated non-crypto bid/ask liquidity;
- exchange-licensed real-time equity data;
- evaluated institutional bond pricing;
- a consolidated FX execution feed;
- a consolidated crypto index; or
- vendor approval for redistribution or user-facing display.

Those gaps remain visible in the readiness report and must fail closed.

## Provider-neutral expansion

Providers not covered by a dedicated adapter can use `providers.configured_dataset.ConfiguredDatasetProvider`. The checked-in example covers all 25 governed market, canonical-screening, and decision-information dataset categories and keeps endpoint schemas, response paths, and credential references outside investment logic. Approved runtime facts are recorded through `run_provider_activation.py`, not by changing source-controlled policy. See [All-Markets Paper Activation](ALL_MARKETS_PAPER_ACTIVATION.md).


## Canonical configured pipeline

The generic landing-zone connector is adapted to investment authorities through:

- `ConfiguredSecurityMasterProvider`;
- `ConfiguredUniverseMetricsProvider`; and
- `ConfiguredCandidateScreeningProvider`.

These adapters require canonical payload schemas and preserve point-in-time identity and availability. They never infer vendor field meanings or convert end-of-day prices into execution quotes. Configure them with the three `CAPITAL_INTELLIGENCE_*_DATASET_BINDING` variables documented in `deploy/external-data.env.example`.
