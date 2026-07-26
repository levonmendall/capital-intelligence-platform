# Capital Intelligence Platform Roadmap

## Current release

Foundation 1.x now has a deployable, observable, backed-up, and operationally
hardened application baseline, a versioned investor-objective and Personal CIO
communication layer, and four reusable analytical engines: Global Liquidity,
Business Cycle, Credit Cycle, and Market Breadth. The next analytical milestone
is Valuation intelligence.

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
- [x] Document briefing meetings versus recommendation governance.
- [ ] Migrate remaining repository callers to canonical committee imports.
- [ ] Move implementation files only after compatibility paths are proven.
- [x] Add append-only regime evidence and decision-quality persistence.
- [ ] Extend the journal to committee, mandate, and portfolio-response events.

## Milestone 2 — Economic-regime productionization

- [x] Map normalized provider observations to regime inputs.
- [x] Add observation dates, vintages, provider provenance, and score lineage.
- [x] Add point-in-time fixtures for every supported regime archetype.
- [x] Add canonical multi-series retrieval with explicit partial failures.
- [ ] Calibrate and version thresholds without look-ahead data.
- [ ] Add regime-transition tests and committee consumption.
- [x] Render a governed CIO decision card as Markdown, JSON, and mobile HTML.
- [ ] Render full analytical regime reports for specialist review.

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
- [x] Define explicit corporate-action, funding-rate, and open-interest records.
- [x] Enforce market-data decision-time and venue boundaries.
- [x] Preserve the legacy latest-quote interface during migration.
- [x] Add current SEC security-master snapshots with ambiguity protection.
- [x] Add offline SEC submissions and company-facts retrieval.
- [x] Enforce SEC acceptance timestamps and preserve amended filings.
- [x] Implement resilient FRED retrieval with caching, rate-limit handling,
  freshness rules, stale-if-error disclosure, and local fixtures.
- [ ] Retrieve older SEC submission archives and dimensional XBRL metadata.
- [ ] Add historical identifiers, corporate actions, and delisted securities
  from a licensed reference provider.
- [ ] Select licensed equity and crypto providers after contract evaluation.
- [ ] Define versioned price-adjustment and cross-venue consolidation policies.
- [ ] Persist complete observation, release, revision, transformation, and
  provenance metadata.
- [ ] Add deterministic fallback and data-quality policies.

Acceptance: tests run without network access and live data is never confused
with cached, fixture, or fallback data.

## Milestone 4 — Macro and market engines

Implement, in order:

1. [x] Global liquidity
2. [x] Business cycle
3. [x] Credit cycle
4. [x] Market breadth
5. [ ] Valuation
6. [ ] Technical and momentum
7. [ ] Risk

Each engine must publish a typed result with score, confidence, coverage,
evidence, risks, and versioned rules. Every engine must feed the Personal CIO
Brief rather than create an independent primary dashboard.

## Milestone 5 — Institutional market decision

- [ ] Normalize engine results.
- [ ] Produce separate opportunity, risk, confidence, and data-quality scores.
- [ ] Configure and version weights.
- [ ] Apply missing-data and veto policies.
- [ ] Submit all engine assessments to committee governance.
- [x] Define append-only thesis lifecycle and falsification triggers.
- [x] Define structured dissent and resolution conditions.
- [x] Make no action a formal terminal committee outcome.
- [x] Define evidence-trust dimensions and disclosed scoring.
- [x] Define scenario shocks and versioned cross-asset transmission maps.
- [x] Compare consecutive regime decisions under versioned materiality rules.
- [x] Separate continuous analysis from selective portfolio alerts.
- [x] Produce plain-language directional portfolio impact.
- [x] Track conviction direction and component drivers across daily snapshots.
- [x] Schedule monitoring cycles and connect user-selected delivery channels.

## Milestone 6 — Stock intelligence

- [x] Establish issuer/listing identity and point-in-time SEC fact models.
- [ ] Build normalized company and financial-statement models.
- [ ] Add quality, strength, growth, earnings-quality, valuation, momentum,
  regime-fit, and company-risk engines.
- [ ] Generate an institutional stock report.
- [ ] Add comparison, ranking, screening, and watchlists.

The uploaded stock v1 archive remains a specification scaffold, not an
implementation baseline.

## Milestone 7 — Portfolio and validation

- [x] Define canonical point-in-time snapshots, positions, proposals, asset
  buckets, and versioned mandate constraints.
- [x] Gate approved proposals through direction, liquidity, concentration,
  cash-reserve, risk-budget, and overlap controls.
- [x] Explain opportunity cost using excess cash and explicit funding candidates.
- [ ] Add portfolio optimization, transaction costs, rebalancing orchestration,
  and paper trading behind the fit gate.
- [ ] Add walk-forward backtests, point-in-time fundamentals, survivorship-bias
  controls, transaction costs, benchmarks, and attribution.
- [x] Separate process quality from realized investment outcome.
- [x] Define disciplined/lucky and flawed/unlucky decision classifications.
- [x] Persist append-only decision-quality reviews.
- [ ] Aggregate learning metrics across reviewed decisions.

## Milestone 8 — Application

- [x] Assemble one canonical daily snapshot from the regime, committee,
  material-change, portfolio-fit, score, environment, and decision-card layers.
- [x] Add append-only score history with prior-snapshot deltas and honest
  current, incomplete, stale, and unavailable states.
- [x] Make Today, Environment, Portfolio, and History the primary Streamlit
  application surfaces.
- [x] Provide a FastAPI boundary for daily snapshots, history, environments,
  decisions, replay artifacts, portfolios, health, and readiness.
- [x] Add append-only Investor Memory and conviction and memory endpoints.
- [x] Add revocable authentication, users, roles, investor ownership, and
  mandate-aware authorization across API and Streamlit surfaces.
- [x] Add idempotent scheduled cycles, authenticated preferences, in-app alerts,
  optional email delivery, deduplication, retries, and delivery history.
- [x] Add container deployment, structured logs, request IDs, metrics, worker
  health, encrypted backups, restore verification, operational runbooks,
  security scanning, and production request hardening.
- [x] Add versioned investor goals and Investment Policy Profiles.
- [x] Add objective-aware Portfolio Alignment without presenting it as a goal
  success probability.
- [x] Add the four-question Personal CIO Brief with formal action and no-action
  outcomes, evidence lineage, and review conditions.
- [x] Add authenticated objective onboarding, objective history, and
  cross-investor authorization.

## Milestone 9 — Personal CIO product contract

- [x] Adopt the Personal CIO North Star in the governing product vision.
- [x] Require primary interactions to answer what changed, why it matters, how it
  affects the portfolio, and whether action is needed.
- [x] Keep Capital Intelligence Score, Conviction Trend, and Portfolio Alignment
  as separate measures with distinct meanings.
- [x] Treat missing objectives as incomplete context rather than inferred facts.
- [x] Treat `no_action` as a formal and valuable recommendation.
- [x] Include investor-objective history in encrypted backups and readiness.
- [x] Feed objective relevance into scheduled alert wording and suppression.
- [x] Link historical Personal CIO Briefs to daily snapshots, policy versions,
  evidence lineage, and Decision Replay references.
