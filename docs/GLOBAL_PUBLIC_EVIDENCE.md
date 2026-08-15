# Global Public Evidence Plane

The free/public global evidence plane broadens product-testing coverage without
changing the platform's investment-authority boundary.

## Operating model

Provider acquisition runs in the non-critical `global-public-evidence` Render
child. The child is deferred while a release diagnostic owns the constrained
Render memory envelope. CIO diagnostics consume qualified persisted evidence;
they do not synchronously crawl these public sources.

The flow is:

`public source -> bounded/resumable acquisition -> immutable page/research evidence -> identity reconciliation queue -> canonical security-master/capability gates`

Retrieval success never activates an instrument. Only the existing certified
security-master, evidence, liquidity/cost, paper-execution and reconciliation
gates may make an instrument decision-eligible or paper-eligible.

## Added discovery/reference sources

- ESMA FIRDS, acquired in bounded pages.
- FCA FIRDS full/delta ZIP/XML, streamed to bounded temporary disk and resumable
  by XML-member and row cursor.
- Nasdaq Trader Nasdaq-listed and other-listed symbol directories.
- JPX and HKEX official catalog slots. Their current official download URLs are
  runtime bindings so a landing-page change cannot silently become data.
- Deribit public active crypto-derivative instrument metadata.

Public catalog pages are content-addressed and appended to a dedicated temporal
security-master store as supporting discovery evidence. They are not activated
for screening.

## Added decision-depth sources

- OECD composite leading indicators through SDMX.
- IMF DataMapper global real-GDP-growth observations.
- BIS credit-to-GDP gap statistics.
- SEC Form 13F structured datasets, streamed and summarized under bounded disk
  and row budgets.
- Companies House issuer profile and filing-history evidence for resolved UK
  candidate company numbers only; there is no whole-register crawl.
- Deribit public futures/options book summaries for open-interest, volume and
  market/risk context.

The repository already contained World Bank, EIA, CFTC Commitments of Traders,
SEC EDGAR, XBRL International, FRED, OpenFIGI, GLEIF and other public adapters;
those integrations are reused instead of duplicated.

## Identity reconciliation

`reconciliation_latest.json` summarizes discovered instruments by source,
country and venue and emits a bounded list of ISINs that lack FIGI mappings.
That list is an enrichment queue only. OpenFIGI/GLEIF evidence can improve
identity resolution in later bounded maintenance, but cannot create screening,
investment or execution authority.

## Runtime configuration

Optional environment variables:

- `CAPITAL_INTELLIGENCE_GLOBAL_PUBLIC_EVIDENCE_INTERVAL_SECONDS`
- `CAPITAL_INTELLIGENCE_PUBLIC_CATALOG_MAX_DOWNLOAD_BYTES`
- `CAPITAL_INTELLIGENCE_FCA_FIRDS_DOWNLOAD_URL`
- `CAPITAL_INTELLIGENCE_JPX_LISTED_CSV_URL`
- `CAPITAL_INTELLIGENCE_HKEX_SECURITIES_CSV_URL`
- `CAPITAL_INTELLIGENCE_SEC_13F_DATASET_URL`
- `COMPANIES_HOUSE_API_KEY`
- `CAPITAL_INTELLIGENCE_COMPANIES_HOUSE_COMPANY_NUMBERS`

`SEC_USER_AGENT` remains required for SEC automated access. JPX/HKEX/FCA source
slots remain dormant rather than scraping HTML when their exact official data
file URL is not configured.

## Authority guarantees

Every global-public maintenance report explicitly states that it has no
screening, decision, investment, execution or real-money authority. Provider
failures degrade only the background lane; they do not bypass fail-closed CIO
readiness and do not authorize fallback data as fresh evidence.
