# Free Decision-Depth Data Tranche

## Objective

Add only free information that closes a known underwriting gap in the global-rotation CIO. Provider count is not an objective. Every source remains evidence-only and must preserve point-in-time availability, provenance, usage rights, freshness, and the existing six-specialist -> CIO -> construction authority chain.

## Keyless sources activated by this tranche

### XBRL International filings.xbrl.org

Gap addressed: **global company fundamentals outside the SEC-centric U.S. path**.

The operating public-source catalog now includes the free public filings.xbrl.org JSON API. Collection is deliberately bounded: it retrieves the newest filing index, follows only a small number of recent xBRL-JSON links, and extracts a conservative set of high-value accounting facts such as revenue, profit/loss, assets, liabilities, equity, cash, operating cash flow, and EPS where those concepts are explicitly tagged.

The repository is not treated as a complete global filing universe. Repository processing/publication metadata is not automatically equivalent to the original regulator's historical availability time, so historical decision reliance remains fail-closed until that timing is certified. Filing evidence never independently authorizes capital.

### U.S. Treasury International Capital (TIC) Form SLT

Gap addressed: **cross-border portfolio capital flows and positioning relevant to FX, sovereign rates, liquidity, and global risk appetite**.

The operating catalog now consumes Treasury's public tab-delimited SLT table for foreign holdings and net U.S. sales of U.S. long-term securities by country. The source is monthly and lagged; it is not represented as a real-time flow tape. Because the table itself does not expose a row-level release timestamp, retrieval time remains the conservative availability boundary until a release-calendar join is certified.

## Keyless source implemented but deliberately disabled

### Coin Metrics Community API

Gap addressed: **on-chain crypto network activity**.

The parser and governed source definition exist, but the source is disabled. The Community API is keyless, while its free tier is designated for non-commercial use. It must not be activated for production until the project's intended use is confirmed compatible with those rights. If activated later, it remains shadow/research evidence until point-in-time history is certified.

## Existing keyless sources that should be expanded rather than duplicated

- **SEC EDGAR** already supplies keyless U.S. submissions and XBRL Company Facts, using the required descriptive `SEC_USER_AGENT`. The next useful SEC enhancement is deeper historical submissions/ownership coverage, not another U.S. filing vendor.
- **IMF DataMapper** is already present as a keyless official global macro source. A duplicate IMF provider would add little value.

## Free sources requiring a user-issued API key — not configured by this tranche

These are intentionally *not* added until the user supplies a free key:

1. **UN Comtrade** — highest-priority key request. Adds global bilateral commodity/product trade flows and materially improves supply-chain, bottleneck, country, commodity, and causal-theme analysis.
2. **Japan EDINET** — adds official Japanese corporate filings and large-shareholding disclosures, materially improving Japanese equity fundamentals and ownership evidence.
3. **U.S. Census International Trade API** — adds detailed monthly U.S. imports/exports by product and partner. If the deployment already has a usable Census API key, the same credential should be reused rather than creating another account.

No key-required source is silently enabled, and no placeholder credential counts as data readiness.

## Keyless source still awaiting a robust machine-data binding

### USGS Mineral Commodity Summaries

The USGS Mineral Commodity Summaries data release is public and public-domain and would materially improve structural mineral supply, production, reserve, and bottleneck evidence. It is not wired in this tranche because the current ScienceBase release should be consumed through a stable, versioned file-distribution binding rather than scraping a landing page. Adding a publication notice alone would not close the commodity-depth gap.

## Gaps not credibly solved by free public data

The project should continue to represent these as incomplete rather than manufacture proxies that appear authoritative:

- point-in-time analyst consensus and revision histories;
- institutional securities lending / borrow availability and fees;
- dealer-level options gamma/positioning;
- complete global direct-bond terms, pricing, default, and recovery histories.

Free public proxies may corroborate those topics, but they must not be mislabeled as institutional-depth replacements.
