# Data Sources and Governance

## Principles

Investment conclusions are only as credible as their data lineage. Every input
must retain its provider, series or field identifier, observation date,
retrieval time, frequency, unit, transformation, revision status, and
point-in-time availability. Missing, stale, revised, fixture, and fallback data
must be distinguishable.

## Initial source registry

| Domain | Preferred source | Example data | Frequency | Point-in-time concern |
| --- | --- | --- | --- | --- |
| Macro | FRED / original agency | GDP, CPI, payrolls, unemployment, claims, production, housing | Daily to quarterly | Many series are revised |
| Policy | FRED / central banks | Policy rates, balance sheets, reserves | Daily to weekly | Release timing differs |
| Credit | FRED and licensed market sources | IG/HY spreads, lending standards, defaults, yield curve | Daily to quarterly | Survey and default revisions |
| Market | Licensed price and crypto providers | Prices, volume, volatility, breadth, funding, open interest | Intraday to daily | Corporate actions, venue fragmentation, 24/7 sessions |
| Fundamentals | SEC filings and licensed normalized source | Statements, shares, guidance | Quarterly | Filing time and restatements |
| Company metadata | SEC and licensed reference source | Industry, geography, identifiers | Event-driven | Identifier and taxonomy changes |

FRED is the first production macro adapter because the repository already has a
client and much of the initial regime evidence is available there. FRED does
not cover every institutional requirement and must not become a universal
provider abstraction.

## Required normalized observation fields

- canonical indicator identifier;
- numeric value and unit;
- observation date;
- release or availability timestamp;
- retrieval timestamp;
- provider and provider-series identifier;
- frequency and transformation;
- vintage or revision identifier when available;
- quality state: live, cached, stale, fixture, fallback, or missing;
- optional prior value and normalized score.

These fields are implemented by `data.NormalizedObservation` and
`data.ObservationProvenance`. Point-in-time consumers must call
`is_available_at` or `require_available_at` before using an observation at a
historical decision timestamp.

## FRED adapter

`providers.fred.FREDProvider` implements the canonical observation-provider
protocol. Requests include an observation end date and FRED's documented
[`vintage_dates` snapshot](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
derived from the query's timezone-aware `as_of` boundary. Canonical series
meaning is stored in
`providers.fred_series.FRED_SERIES`, not embedded in HTTP parsing code.

FRED real-time metadata is date-granular. The adapter therefore treats a
provider vintage date as available at the end of that UTC day. If FRED omits
the vintage date, the retrieval timestamp becomes a conservative availability
proxy and the provenance records `retrieval_proxy`.

FRED retrieval is governed by `FREDRetrievalPolicy`. Successful responses are
cached under a deterministic request fingerprint that excludes the API key.
Fresh cache hits are disclosed as `cached`; an expired response may be used as
`stale` only after retryable provider failures and only within the configured
stale-if-error window. Rate limits, transient server responses, and transport
errors use bounded exponential backoff. Non-retryable client errors fail
immediately.

`MemoryFREDCache` supports short-lived workers and deterministic tests.
`JsonFREDCache` provides an atomic, human-inspectable local snapshot that can be
seeded as an offline fixture. Cached responses retain their original retrieval
timestamp, so a fallback never masquerades as newly retrieved evidence.
Credentials are neither serialized nor included in cache identity.

## Regime evidence transformation

The first versioned regime rule set, `fred-us-v1`, uses official FRED series
with distinct economic meanings:

| Signal | FRED series | Transformation |
|---|---|---|
| Growth | INDPRO | Year-over-year percent change in industrial production |
| Inflation | CPIAUCSL | Year-over-year CPI inflation relative to a 2% anchor |
| Policy | FEDFUNDS + CPIAUCSL | Real federal-funds stance |
| Liquidity | WALCL | Year-over-year change in Federal Reserve total assets |
| Financial stress | STLFSI4 | Current stress-index level |

All scores are clipped to the regime engine's `[-1, 1]` contract. The
transformation constants are explicit fields of `RegimeScoringRules`; changing
one requires a new version rather than silently rewriting prior decisions.
Every computed signal retains observation date, release time, retrieval time,
provider, series identifier, quality state, and raw value.

Evidence identity is provider-qualified: the initial rule set accepts
`("FRED", series_identifier)` inputs rather than trusting a bare series name.
Year-over-year comparisons select the observation nearest the prior-year
anniversary inside an explicit tolerance. This matters for weekly series such
as WALCL, where matching by calendar month can create an inconsistent
comparison window.

The version-controlled fixtures exercise historically recognizable regime
archetypes but are deterministic scenarios, not claims to reproduce an official
historical vintage. Empirical calibration against archived ALFRED vintages
remains a separate milestone.

## SEC EDGAR adapter

`providers.sec_edgar.SECEdgarProvider` uses the SEC's official
[submissions and XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and its ticker-exchange reference file. It requires `SEC_USER_AGENT` to contain
a descriptive application identity and contact address, consistent with the
SEC's automated-access policy; no API key is required.

The adapter provides three bounded capabilities:

- a current security-master snapshot keyed by canonical ten-digit CIK;
- recent filing metadata from the company's submissions payload;
- company facts joined to filing acceptance timestamps by accession number.

SEC tickers are venue-listing attributes, not permanent issuer identifiers. The
adapter maps each CIK to an issuer and each exchange-ticker row to a generic
instrument and venue listing. The SEC feed does not authoritatively classify
every row as common stock, ETF, or another instrument type, so those fields
remain unclassified until a reference provider supplies them. The current
reference file is not historical security-master data, so its retrieval
timestamp is recorded as the observation boundary. Historical ticker changes,
delistings, and corporate actions require a licensed reference source later.

For point-in-time analysis, `acceptanceDateTime` is authoritative. Calendar
filing dates are retained for reporting but never used as an intraday
availability proxy. XBRL facts whose accession number cannot be joined to an
accepted filing are excluded. Original and amended forms are both preserved;
downstream restatement policy must choose between them explicitly.

The initial adapter covers the `filings.recent` section of the submissions
payload. Older submission archive files, filing-document parsing, dimensional
XBRL normalization, and network resilience remain separate milestones.

## Crypto market requirements

Crypto is a first-class market domain, not an equity symbol extension. Canonical
identity supports spot tokens, stablecoins, futures, and perpetual contracts;
network-scoped contract addresses; base, quote, and settlement assets; and
venue-specific symbols. Crypto venue listings use an explicit continuous 24/7
calendar.

Future crypto providers must preserve exchange identity because prices, volume,
funding, open interest, liquidations, and even instrument definitions vary by
venue. Consolidated values must retain their contributing venues and
methodology. On-chain observations require chain, network, block height or
timestamp, finality assumptions, and reorganization policy. Custody,
counterparty, stablecoin, bridge, oracle, and regulatory risks remain separate
from ordinary market-price risk.

## Market-data contract

`data.market` defines bounded queries and immutable records for quotes, trades,
OHLCV bars, corporate actions, funding rates, and open interest. It supports
exchange-session equities and continuously traded crypto instruments without
assuming that a symbol identifies the same market across venues.

The initial milestone is contract-only and deliberately has no live vendor.
Provider selection follows offline contract validation. Adjusted prices are not
canonical raw evidence: providers must retain raw bars and corporate actions so
the platform can apply a named, versioned adjustment policy. Cross-venue crypto
prices are derived observations and must disclose constituents, weighting,
outlier policy, timestamp tolerance, and missing-venue behavior.

## Provider behavior

Providers must use explicit timeouts, bounded retries with backoff, rate-limit
handling, schema validation, and actionable exceptions. Caches use keys that
include provider, series, transformation, vintage, and date range. Freshness is
defined per series rather than globally.

## Point-in-time policy

Backtests may only consume information available at the simulated decision
time. Revised macro history and restated company filings require their original
vintage or an explicit limitation label. When point-in-time data is
unavailable, the backtest must report the resulting bias.

## Missing-data policy

- Missing inputs lower data coverage and confidence.
- Core missing inputs may force a `Transition` or `Unavailable` conclusion.
- Values are never silently imputed.
- Any approved imputation method is versioned and disclosed in the result.
- Fixture and fallback data are labeled in application and report outputs.

## Credentials and licensing

API keys stay in environment variables or GitHub secrets. Source licensing,
redistribution rights, retention limits, and derived-data permissions must be
reviewed before a provider is enabled outside development.
