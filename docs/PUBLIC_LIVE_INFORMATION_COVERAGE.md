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

The public live stack includes:

1. **GDELT DOC 2.0** for global news-discovery metadata and links. It is a discovery and corroboration aid, not a substitute for an original source or licensed journalism archive.
2. **Federal Reserve Board** and **European Central Bank** feeds for monetary-policy, liquidity, regulatory, and central-bank communications.
3. **SEC press releases** and the **Federal Register API** for securities enforcement, formal U.S. rules, notices, executive actions, and regulatory changes.
4. **OFAC Sanctions List Service** for the SDN list and consolidated non-SDN restrictions. Matches require governed entity resolution and program-specific legal interpretation.
5. **CFTC public reporting** for weekly futures and commodity positioning.
6. **National Weather Service**, **OpenFEMA**, and **USGS** for active hazards, official disaster declarations, and earthquakes.
7. **NASA FIRMS** for global near-real-time active-fire detections when a free `NASA_FIRMS_MAP_KEY` is configured.
8. **CISA Known Exploited Vulnerabilities** for authoritative cyber-risk developments.
9. **openFDA food, drug, and medical-device enforcement data** for recalls and supply-chain, health, legal, and issuer-risk evidence.
10. **World Health Organization Disease Outbreak News** for confirmed or potentially material international public-health events.
11. **U.S. Treasury Fiscal Data**, **World Bank Indicators**, and **IMF DataMapper** for fiscal and global macroeconomic context.
12. **EIA Open Data** for energy prices and physical-market evidence when a free `EIA_API_KEY` is configured.

The public stack complements the existing FRED, SEC EDGAR, Coinbase, Kraken, and optional EODHD adapters.

## Required versus optional sources

The required baseline contains stable, high-impact official sources that need no new credential, plus SEC access using the existing descriptive user agent. A required-source outage marks the public baseline as degraded, preserves the exact source failures in the uploaded evidence, and emits a GitHub Actions warning. It does not mark the application or listed-wrapper paper launch as failed.

Optional sources are still attempted every hour but do not stop the required baseline. They include free-key services and endpoints that need operating burn-in, including NASA FIRMS, EIA, WHO, IMF, openFDA, and the OFAC consolidated non-SDN export. Their failures remain visible in the report.

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

Retrieval time is used as a conservative availability boundary when a source does not provide a precise first-availability timestamp. Future scheduled events are retained as tagged metadata without making them appear to have already occurred.

## Reliability policy

Public-source breadth does not create investment authority. The platform must:

- prefer original official records;
- treat GDELT as metadata discovery rather than verified fact;
- avoid storing article bodies without contractual rights;
- distinguish an event from reporting about that event;
- deduplicate normalized records by deterministic content hash;
- retain source limitations;
- perform entity, geography, product, issuer, and portfolio-exposure mapping;
- require market confirmation and CIO review before a material event can change a portfolio decision;
- keep paid newswire and independent-journalism requirements visible in the maximum-information readiness gate.

Sanctions, recalls, disaster declarations, vulnerabilities, and fire detections are evidence of a condition or official action. They are not, by themselves, proof of portfolio loss, issuer exposure, expected return, or a trade requirement.

Repeated syndicated copies do not count as independent evidence.

## Scheduled operation

`.github/workflows/public-live-information.yml` runs hourly and on demand. It performs two passes:

1. a required public baseline whose availability state is recorded; and
2. a full pass that also attempts optional and free-key sources.

Temporary upstream outages produce a degraded warning rather than a failed application check. A collector implementation failure, invalid catalog, or other inability to produce trustworthy evidence still fails the workflow. Missing public evidence never becomes positive evidence: any CIO decision that depends on an unavailable source remains blocked or abstains under the normal point-in-time controls.

The workflow uploads credential-safe reports and normalized records as a 14-day artifact. Production deployment should run the same CLI from a persistent scheduler and write the report paths to durable storage.

The latest persisted report is available through:

```text
GET /v1/governance/public-live-information
```

The combined governance route also exposes public source and record counts:

```text
GET /v1/governance/data-readiness
```

## Configuration

```text
CAPITAL_INTELLIGENCE_PUBLIC_LIVE_SOURCE_CATALOG=config/public_live_information_sources.json
CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT=database/public-live-information-report.json
SEC_USER_AGENT=Capital Intelligence Platform <monitored-contact>
```

Optional free keys:

```text
EIA_API_KEY=<free EIA key>
NASA_FIRMS_MAP_KEY=<free NASA FIRMS map key>
```

The source catalog contains no secret values. Credential placeholders in URL paths and parameters are substituted only at runtime, and failures are redacted before reports are written.

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
- full global crop, power-grid, physical commodity, and weather-model coverage;
- consolidated on-chain labels and crypto derivatives data.

Those sources remain explicit provider-onboarding requirements. The platform does not mark maximum decision-information readiness complete merely because the public layer is operating.
