# Maximum Public Live Information Coverage

## Purpose

The maximum decision-information manifest defines the full institutional target. This public live layer activates the widest reliable coverage that can be used immediately without pretending that unpaid public endpoints replace licensed newswires, exchange feeds, analyst estimates, transcripts, or proprietary alternative data.

The governing source catalog is:

```text
config/public_live_information_sources.json
```

The collection command is:

```bash
python run_public_live_information.py \
  --output database/public-live-information-report.json \
  --records-output database/public-live-information-records.json
```

The report is credential-safe. The normalized record set contains metadata, official records, summaries, links, timestamps, provenance, impact channels, and content hashes. It does not store full copyrighted article text.

## Live sources

The initial public live stack includes:

1. **GDELT DOC 2.0** for global news discovery metadata and links. GDELT is a discovery and corroboration aid, not a substitute for an original source or licensed journalism archive.
2. **Federal Reserve Board RSS** for U.S. monetary-policy, regulatory, liquidity, and central-bank communications.
3. **European Central Bank RSS** for euro-area policy, speeches, releases, and central-bank communications.
4. **SEC press-release RSS** for U.S. securities regulation, enforcement, legal events, and corporate-disclosure developments.
5. **CFTC public reporting** for weekly futures and commodity positioning.
6. **National Weather Service alerts** for active U.S. weather hazards.
7. **USGS earthquake GeoJSON** for near-real-time earthquake events.
8. **CISA Known Exploited Vulnerabilities** for authoritative cyber-risk developments.
9. **U.S. Treasury Fiscal Data** for current federal fiscal and debt observations.
10. **World Bank Indicators API** for broad global macro context.
11. **EIA Open Data** for energy prices and physical-market evidence when a free `EIA_API_KEY` is configured.

The public stack complements the existing live FRED, SEC EDGAR, Coinbase, and Kraken adapters and the optional EODHD commercial adapter.

## Point-in-time behavior

Every normalized live record preserves:

- source and source-record identity;
- event or observation time;
- source publication time when supplied;
- platform retrieval and availability time;
- decision knowledge cutoff;
- source type and independence group;
- licensing and usage-right identifiers;
- a raw-record content hash;
- quality state;
- entities, geographies, topics, and domains;
- explicit portfolio-impact channels;
- reliability, relevance, and materiality scores;
- declared limitations.

Retrieval time is used as a conservative availability boundary when a source does not provide a precise first-availability timestamp.

## Reliability policy

Public-source breadth does not create investment authority. The platform must:

- prefer original official records;
- treat GDELT as metadata discovery rather than verified fact;
- avoid storing article bodies without contractual rights;
- distinguish an event from reporting about that event;
- deduplicate normalized records by deterministic content hash;
- retain source limitations;
- require market confirmation and CIO review before a material event can change a portfolio decision;
- keep paid newswire and independent-journalism requirements visible in the maximum-information readiness gate.

Repeated syndicated copies do not count as independent evidence.

## Scheduled operation

`.github/workflows/public-live-information.yml` runs hourly and on demand. It performs two passes:

1. a required public baseline that must succeed; and
2. a full pass that also attempts optional free-key sources such as EIA.

The workflow uploads credential-safe reports and normalized records as a 14-day artifact. Production deployment should run the same CLI from its persistent scheduler and write the report paths to durable storage.

The latest persisted report is available through:

```text
GET /v1/governance/public-live-information
```

The combined governance route also exposes public source and record counts:

```text
GET /v1/governance/data-readiness
```

## Required configuration

```text
CAPITAL_INTELLIGENCE_PUBLIC_LIVE_SOURCE_CATALOG=config/public_live_information_sources.json
CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT=database/public-live-information-report.json
SEC_USER_AGENT=Capital Intelligence Platform <monitored-contact>
```

Optional:

```text
EIA_API_KEY=<free EIA key>
```

The source catalog contains no secret values.

## Remaining paid coverage

Maximum public live coverage still cannot provide:

- licensed global newswire archives and correction histories;
- contractually independent full-text journalism;
- global earnings-call transcripts and analyst estimates;
- exchange-licensed real-time equity, futures, option, and FX data;
- institutional bond pricing and evaluated liquidity;
- authoritative historical global security-master and corporate-action data;
- proprietary fund flows, securities lending, short interest, and ownership datasets;
- comprehensive shipping, satellite, card-spending, app, web, and employment alternative data;
- full global weather, crop, power-grid, and physical commodity coverage;
- consolidated on-chain labels and crypto derivatives data.

Those sources remain explicit provider-onboarding requirements. The platform does not mark maximum decision-information readiness complete merely because the public layer is operating.
