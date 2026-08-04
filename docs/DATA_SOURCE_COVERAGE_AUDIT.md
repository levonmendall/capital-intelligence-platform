# Data Source Coverage Audit

## Purpose

This audit records which data sources are already implemented, which additional public sources are now connected, and which external datasets still require user procurement and provider certification.

Connectivity is not provider certification. Public-information records remain advisory and cannot create candidates, qualify opportunities, size positions, authorize CIO action, execute orders, or enable live money.

## Already implemented before this audit

The repository already contains adapters or governed connection paths for:

- Alpaca market data and paper brokerage;
- SEC EDGAR and Company Facts;
- FRED and its point-in-time cache;
- EODHD broad historical multi-asset data;
- Databento equities, futures, options, contract and execution evidence;
- Coinbase Exchange and Kraken spot validation;
- OpenFIGI instrument mapping;
- GLEIF legal-entity identity;
- Alpha Vantage and Twelve Data supplemental quote fallback;
- GDELT discovery metadata;
- Federal Reserve and ECB communications;
- SEC press releases and Federal Register documents;
- OFAC sanctions data;
- CFTC positioning;
- Treasury fiscal data;
- World Bank and IMF macro observations;
- EIA energy data;
- NWS, FEMA, USGS, NASA FIRMS, CISA, OpenFDA and WHO event feeds.

The repository also already defines—but does not automatically activate—contracted institutional bindings for LSEG market/reference/fundamental data, ICE evaluated fixed-income data, CME/OCC/ICE margin data and derived volatility surfaces.

## Sources added by this audit

The public-information catalog now includes:

1. U.S. Bureau of Labor Statistics CPI observations through the keyless BLS API.
2. Federal Reserve Bank of New York SOFR reference rates.
3. U.S. Treasury daily par yield-curve rates.
4. ECB Data Portal EUR/USD observations.
5. Eurostat euro-area quarterly GDP observations.
6. U.S. Bureau of Economic Analysis national accounts.
7. U.S. Census Bureau economic indicators.

The runtime now supports BLS JSON, New York Fed reference-rate JSON, Treasury Atom/XML, generic SDMX CSV, Eurostat JSON-stat, BEA JSON and Census tabular JSON. Dynamic current-date placeholders keep bounded official queries current without hard-coded annual maintenance.

These feeds strengthen supporting economic context but do not, by themselves, activate comprehensive all-market data readiness or replace certified point-in-time institutional datasets.

### Additional sources added after the concurrent baseline merge

A second non-duplicative pass adds:

- Bank of England news and statistical-release feeds;
- Bank of Japan official updates;
- Bank of Canada press releases;
- Swiss National Bank monetary-policy releases;
- BIS statistical-release notices;
- Eurostat statistical-release notices;
- BLS unemployment and total nonfarm payroll observations;
- the ECB deposit-facility policy rate;
- Eurostat harmonised inflation;
- OECD composite leading indicators for material economies;
- USDA NASS crop-production observations.

The catalog now contains 41 governed public sources. These additions improve independent
policy, labor, inflation, leading-indicator and physical-commodity evidence while
remaining outside candidate, vote, sizing, construction and execution authority.

## Deployment corrections

Render now declares the checked-in EODHD, Databento and crypto binding files and exposes secret slots for adapters that already existed but were not represented in the deployment blueprint:

- `OPENFIGI_API_KEY`
- `ALPHA_VANTAGE_API_KEY`
- `TWELVE_DATA_API_KEY`
- `EIA_API_KEY`
- `NASA_FIRMS_MAP_KEY`
- `BEA_API_KEY`
- `CENSUS_API_KEY`
- `USDA_NASS_API_KEY`

Missing optional credentials leave only the affected optional source unavailable. They do not grant readiness or permit degraded evidence to be treated as complete.

## Sources the user still needs to obtain

### Free or low-cost credentials

Obtain these only when not already configured in Render:

- BEA API key;
- Census API key;
- USDA NASS Quick Stats API key;
- EIA API key;
- NASA FIRMS map key;
- OpenFIGI API key for higher mapping limits;
- Alpha Vantage API key and Twelve Data API key for independent supplemental quote fallback.

The existing Alpaca, FRED, EODHD and Databento credentials must also remain valid, but those adapters were already present before this audit.

### Contracted institutional datasets

The following capabilities cannot be truthfully activated from public endpoints alone and still require contracts, rights review, point-in-time validation and certification:

- global execution-grade market prices, quotes and liquidity;
- historical global security master and corporate actions;
- normalized global fundamentals, filings and estimates;
- evaluated fixed-income prices, curves, duration, spreads and liquidity;
- futures and options clearing margin parameters;
- consensus earnings estimates and revisions;
- consensus macro expectations and surprise history;
- ETF and mutual-fund flows;
- institutional credit issuance and liquidity;
- options volatility surfaces, skew and positioning beyond derived public proxies;
- short interest and securities lending;
- institutional ownership changes;
- cross-border capital flows;
- buybacks, issuance and insider transaction datasets;
- institutional crypto exchange flows, stablecoin movement, derivatives funding, open interest and liquidations;
- dealer positioning;
- validated supply-chain, industry and alternative datasets.

Existing configuration names LSEG for global market/reference/fundamental coverage, ICE for evaluated fixed income, Databento for direct exchange data, and CME/OCC/ICE for margin inputs. A different vendor may be selected only if it satisfies the same governed domains and certification controls.

## Activation requirement

Every externally obtained dataset must pass licensing and allowed-use review, point-in-time and historical-coverage checks, provenance and instrument-identity reconciliation, freshness and outage controls, deterministic fixtures, certification scenarios, data-readiness activation and fail-closed production binding. An API response alone is not activation evidence.
