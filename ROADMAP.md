# Capital Intelligence Platform Roadmap

## Current release

Foundation 1.x is the validated baseline in GitHub. The active milestone is
canonical application integration around the daily intelligence experience.

## Milestone 1 — Consolidated foundation

- [x] Identify the authoritative GitHub repository.
- [x] Audit external architecture, regime, and stock packages.
- [x] Reject placeholder packages as release inputs.
- [x] Add governing architecture, roadmap, data, and decision documents.
- [x] Add an explainable economic-regime bounded context.
- [x] Preserve the legacy allocation interface through a compatibility facade.
- [x] Establish the CI baseline on the integration pull request.

Acceptance: the full repository test suite passes; no working implementation is
replaced by a placeholder; the pull request documents the observed baseline.

## Architecture stabilization

- [x] Establish `committee` as the owner of collective governance.
- [x] Add an ownership-correct recommendation-governance facade.
- [x] Add a canonical recommendation-to-result workflow.
- [x] Preserve existing intelligence imports during migration.
- [x] Document the distinction between briefing meetings and recommendation
  governance.
- [ ] Migrate repository callers to canonical committee imports.
- [ ] Move implementation files only after compatibility paths are proven.
- [x] Add append-only regime evidence and decision-quality persistence.
- [ ] Extend the journal to committee, mandate, and portfolio-response events.

## Milestone 2 — Economic-regime productionization

- [x] Map normalized provider observations to regime inputs.
- [x] Add observation dates, vintages, provider provenance, and score lineage.
- [x] Add point-in-time fixtures for every supported regime archetype.
- [x] Add canonical multi-series retrieval with explicit partial failures.
- Calibrate and version thresholds without look-ahead data.
- Add regime-transition tests and committee consumption.
- [x] Render a governed CIO decision card as Markdown, JSON, and mobile HTML.
- Render full analytical regime reports for specialist review.

Acceptance: at least one historically representative fixture exists for every
supported regime, classifications are reproducible, and missing data cannot
produce false precision.

## Milestone 3 — Data foundation

- [x] Define strict normalized observation and provenance models.
- [x] Add point-in-time availability and revision identity.
- [x] Add explicit live, cached, stale, fixture, fallback, and missing states.
- [x] Preserve the legacy state-engine observation contract with an adapter.
- [x] Define provider-neutral query and series contracts.
- [x] Implement a canonical FRED adapter with point-in-time boundaries.
- [x] Record whether availability uses provider dates or retrieval proxies.
- [x] Add a version-controlled registry for foundation FRED series.
- [x] Add canonical issuer, listing, filing, and company-fact contracts.
- [x] Generalize identity across equities, funds, fixed income, FX,
  commodities, and crypto.
- [x] Separate issuer identity, instrument identity, and venue symbols.
- [x] Support crypto networks, contract addresses, trading pairs,
  perpetuals, and continuous 24/7 listings.
- [x] Define provider-neutral quotes, trades, and OHLCV bars.
- [x] Define explicit corporate-action, funding-rate, and open-interest
  records.
- [x] Enforce market-data decision-time and venue boundaries.
- [x] Preserve the legacy latest-quote interface during migration.
- [x] Add current SEC security-master snapshots with ambiguity protection.
- [x] Add offline SEC submissions and company-facts retrieval.
- [x] Enforce SEC acceptance timestamps and preserve amended filings.
- [x] Implement resilient FRED retrieval with caching, rate-limit handling,
  freshness rules, stale-if-error disclosure, and local fixtures.
- Retrieve older SEC submission archive files and dimensional XBRL metadata.
- Add historical identifiers, corporate actions, and delisted securities from
  a licensed reference provider.
- Select licensed equity and crypto market-data providers after contract
  evaluation.
- Define versioned price-adjustment and cross-venue consolidation policies.
- Persist observation time, release time, revision/vintage, unit, frequency,
  transformation, and provenance.
- Add deterministic fallback and data-quality policies.

Acceptance: tests run without network access and live data is never confused
with cached, fixture, or fallback data.

## Milestone 4 — Macro and market engines

Implement, in order:

1. Global liquidity
2. Business cycle
3. Credit cycle
4. Market breadth
5. Valuation
6. Technical and momentum
7. Risk

Each engine must publish a typed result with score, confidence, coverage,
evidence, risks, and versioned rules.

Market-data contracts must support exchange-session and 24/7 instruments,
venue-specific spot and derivative prices, quote and settlement currencies,
funding rates, open interest, liquidations, and explicitly governed
cross-venue consolidation.

## Milestone 5 — Institutional market decision

- Normalize engine results.
- Produce separate opportunity, risk, confidence, and data-quality scores.
- Configure and version weights.
- Apply missing-data and veto policies.
- Submit assessments to committee governance.
- [x] Define append-only thesis lifecycle and falsification triggers.
- [x] Define structured dissent and resolution conditions.
- [x] Make no action a formal terminal committee outcome.
- [x] Define evidence-trust dimensions and disclosed scoring.
- [x] Define scenario shocks and versioned cross-asset transmission maps.
- [x] Compare consecutive regime decisions under versioned materiality rules.
- [x] Separate continuous analysis from selective portfolio alerts.
- [x] Produce plain-language directional portfolio impact.
- Schedule monitoring cycles and connect user-selected delivery channels after
  application authentication is implemented.

## Milestone 6 — Stock intelligence

- [x] Establish issuer/listing identity and raw point-in-time SEC fact models.
- Build normalized company and financial-statement models from canonical facts.
- Add quality, financial strength, growth, earnings quality, valuation,
  momentum, regime-fit, and company-risk engines.
- Generate an institutional stock report.
- Add comparison, ranking, screening, and watchlists.

The uploaded stock v1 archive is a specification scaffold, not an
implementation baseline.

## Milestone 7 — Portfolio and validation

- [x] Define canonical point-in-time snapshots, positions, proposals, asset
  buckets, and versioned mandate constraints.
- [x] Gate approved proposals through direction, liquidity, concentration,
  cash-reserve, risk-budget, and overlap controls.
- Add portfolio optimization, transaction costs, rebalancing orchestration,
  and paper trading behind the fit gate.
- Add walk-forward backtests, point-in-time fundamentals, survivorship-bias
  controls, transaction costs, benchmarks, and attribution.
- [x] Separate process quality from realized investment outcome.
- [x] Define disciplined/lucky and flawed/unlucky decision classifications.
- [x] Persist append-only decision-quality reviews.
- Aggregate learning metrics across reviewed decisions.

## Milestone 8 — Application

- [x] Assemble one canonical daily snapshot from the regime, committee,
  material-change, portfolio-fit, score, environment, and decision-card layers.
- [x] Add append-only score history with prior-snapshot deltas and honest
  current, incomplete, stale, and unavailable states.
- [x] Make Today, Environment, Portfolio, and History the primary Streamlit
  application surfaces.
- Provide FastAPI endpoints for assessments, reports, committee decisions,
  portfolios, daily snapshots, and history.
- Add authentication, authorization, scheduled monitoring, user-selected
  alerts, and deployment.
