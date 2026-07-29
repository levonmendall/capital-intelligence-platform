# Provider Productionization

This layer turns authenticated provider credentials into governed runtime evidence without pretending that credentials grant licensing, certification, or investment authority.

## Implemented providers

- **Databento** now has a native HTTP JSON Lines adapter for quotes, trades, minute, five-minute, hourly, and daily bars. It can also retain raw market-history, quote/liquidity, derivative-definition, market-status, benchmark, and execution-input datasets as immutable provider snapshots.
- **EODHD** retains its existing canonical daily-bar and corporate-action adapter. `run_eodhd_binding_expansion.py` can now generate a broad secret-free research binding file from licensed active and optional delisted symbol directories.
- **Alpha Vantage and Twelve Data** can be compared through `run_supplemental_quote_crosscheck.py`. Their observations are corroborating evidence only and cannot authorize execution.
- **Runtime diagnostics** identify which credential aliases and binding files are available in GitHub Actions, Streamlit, or another named runtime without exposing values.
- **Technical certification** combines credential validation, runtime integration, Databento capability discovery, and an optional EODHD binding manifest. The report explicitly leaves provider activation, asset-class paper approval, and real-money authority false.

## Databento

The default secret-free mapping is:

```text
config/databento_instrument_bindings.all_markets.json
```

Override it with:

```bash
export CAPITAL_INTELLIGENCE_DATABENTO_INSTRUMENT_BINDINGS=/run/secrets/databento-instrument-bindings.json
```

Inspect the account and every configured binding:

```bash
python run_databento_catalog.py \
  --output reports/databento-capability-report.json
```

The adapter uses Databento Basic Authentication and `timeseries.get_range` with JSON Lines, pretty prices, pretty timestamps, and mapped symbols. A successful request proves technical access only.

## EODHD directory expansion

Generate a reviewed research universe from one or more licensed exchange directories:

```bash
python run_eodhd_binding_expansion.py \
  --exchange US \
  --exchange LSE \
  --seed-bindings config/eodhd_instrument_bindings.all_markets.json \
  --output data/provider-bindings/eodhd-expanded.json
```

Add `--include-delisted` only when the resulting directory will be retained and reconciled as research evidence. The generated file is not a survivorship-safe security master and cannot itself make an asset paper eligible.

## Supplemental quote corroboration

```bash
python run_supplemental_quote_crosscheck.py \
  --symbol AAPL \
  --maximum-divergence-bps 250 \
  --output reports/supplemental-quote-crosscheck.json
```

A disagreement lowers confidence in the supplemental evidence. It does not replace Alpaca, Databento, or another certified execution-grade source.

## Runtime diagnostics

Run separately in each deployment environment:

```bash
python run_provider_runtime_diagnostics.py \
  --environment-name github_actions \
  --output reports/github-actions-provider-runtime.json
```

```bash
python run_provider_runtime_diagnostics.py \
  --environment-name streamlit_runtime \
  --output reports/streamlit-provider-runtime.json
```

Merge the reports:

```bash
python run_provider_runtime_diagnostics.py \
  --environment-name local_runtime \
  --merge-report reports/github-actions-provider-runtime.json \
  --merge-report reports/streamlit-provider-runtime.json \
  --output reports/provider-runtime-matrix.json
```

Only environment-variable names, file paths, states, and blockers are reported. Secret values are never serialized.

## Technical certification

```bash
python run_provider_technical_certification.py \
  --credential-report reports/provider-secret-validation.json \
  --runtime-report reports/provider-runtime-diagnostics.json \
  --databento-report reports/databento-capability-report.json \
  --eodhd-binding-manifest data/provider-bindings/eodhd-expanded.json \
  --output reports/provider-technical-certification.json \
  --require-technical-ready
```

`technical_ready_legal_pending` means the adapters, credentials, bindings, and technical probes are functioning. It does **not** mean contracts, storage rights, exchange entitlements, paper-simulation permissions, provider activation, or asset-class approvals have been granted.

## Automated evidence

The `Provider Productionization` GitHub workflow runs focused tests, validates the configured secrets, publishes runtime diagnostics, discovers Databento capabilities, cross-checks AAPL through the supplemental sources, assembles a technical certification, and uploads only credential-safe JSON evidence.
