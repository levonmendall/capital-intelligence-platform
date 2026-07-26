# Capital Intelligence Platform Roadmap

> [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md) is the binding product and engineering contract.

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Governing objective

> **Maximize long-term compounded portfolio returns.**

Risk, liquidity, concentration, correlation, factor exposure, turnover, costs, leverage, drawdown, evidence quality, data freshness, and implementation feasibility are protective constraints. Individual financial goals and personalized investment philosophies are excluded from the active investment process.

## Current release state

The canonical institutional CIO architecture is implemented:

- point-in-time evidence and provenance contracts;
- Version 1 eligibility controls;
- quantitative candidate records;
- comparison with cash, holdings, and other capital alternatives;
- qualification and opportunity ranking;
- five independent specialists plus CIO authority;
- portfolio-level construction and funding;
- append-only decision, construction, thesis, and evaluation history;
- continuous living-thesis review;
- point-in-time outcome evaluation, attribution, and confidence calibration;
- score-free Daily Capital Intelligence and a canonical read-only API; and
- authentication, authorization, security, deployment, and backup controls.

The remaining roadmap is primarily data breadth, empirical validation, monitoring orchestration, paper-trading governance, and production operations—not creation of a second decision architecture.

## Milestone 1 — Governing product realignment

- [x] Adopt one objective: maximize long-term compounded portfolio returns.
- [x] Make the consolidated specification authoritative.
- [x] Remove goals, required returns, retirement targets, preferences, and behavioral memory from the active decision path.
- [x] Preserve historical personal records only as isolated migration data.
- [x] Replace Personal CIO product and API authority with Capital Intelligence CIO terminology.
- [x] Replace objective-aware alignment with measurable portfolio contribution and improvement.
- [x] Demote the Capital Intelligence Score to deprecated diagnostic context.
- [x] Add architecture tests protecting the active decision graph.
- [ ] Add repository PR-template automation that explicitly cites every governing invariant.

## Milestone 2 — Decision integrity and point-in-time evidence

- [x] Normalize observation, filing, security, and market provenance.
- [x] Preserve publication, retrieval, vintage, acceptance, and availability boundaries.
- [x] Disclose live, cached, stale, fixture, fallback, and missing states.
- [x] Preserve evidence quality dimensions, identifiers, model versions, schema versions, and code versions.
- [x] Add append-only hash-chained CIO history.
- [x] Freeze every decision’s complete evidence package and original alternative set.
- [x] Add point-in-time replay and look-ahead rejection tests.
- [x] Add a temporal identifier, listing, delisting, corporate-action, and append-only catalog substrate with cutoff-aware replay.
- [x] Add provider-neutral delivery timestamps, deterministic source reconciliation, coverage diagnostics, and append-only ingestion history.
- [ ] Add licensed historical identifiers, corporate actions, delisted securities, and complete cross-venue adjustment policy.
- [ ] Expand derivative-evidence lineage and source-family de-duplication across every production provider.

## Milestone 3 — Version 1 recommendation universe

- [x] Add a versioned recommendation-universe policy.
- [x] Require supported U.S. listing, instrument type, liquidity, freshness, and analytical coverage.
- [x] Distinguish evidence-only assets from recommendation-eligible assets.
- [x] Block unsupported asset classes from ranking, CIO action, sizing, and implementation.
- [x] Retain broader markets as evidence and regime inputs.
- [x] Test eligibility and blocking behavior.
- [x] Build validated point-in-time security-master snapshots and Version 1 membership with explicit authoritative-coverage gating.
- [x] Add expiring activation that prevents incomplete, stale, conflicting, or integrity-invalid catalogs from powering screening.
- [ ] Operate a complete production-quality point-in-time security master for the full eligible universe.

## Milestone 4 — Common candidate decision schema

- [x] Use a comparable quantitative candidate record.
- [x] Require current price, horizon, base/bull/bear returns, and scenario probabilities.
- [x] Calculate probability-weighted and cost-adjusted expected return.
- [x] Require fair value, upside, downside, and probability of success.
- [x] Require catalysts, risks, assumptions, invalidation conditions, and monitoring indicators.
- [x] Require supporting and contradictory evidence with quality and freshness.
- [x] Require liquidity, costs, slippage, opportunity cost, and portfolio contribution.
- [x] Preserve specialist conclusions, vetoes, implementation blocks, and dissent.
- [x] Require final CIO confidence, action, proposed size, and review date.
- [x] Version, serialize, persist, replay, and evaluate the schema.

## Milestone 5 — Opportunity detection and ranking

- [x] Normalize company and financial-statement models from accepted SEC facts.
- [x] Add quality, financial strength, growth, earnings quality, valuation, momentum, regime-fit, and company-risk factors.
- [x] Estimate expected return, downside, success probability, evidence quality, liquidity, and costs.
- [x] Compare every candidate with cash, current holdings, and all supplied alternatives.
- [x] Rank by return, downside, evidence, liquidity, costs, opportunity cost, and portfolio contribution.
- [x] Reject weak, stale, redundant, illiquid, cost-disadvantaged, or infeasible candidates before committee review.
- [x] Detect replacement opportunities and weakening active theses.
- [x] Build reproducible Version 1 universe snapshots from security-master identity plus point-in-time liquidity and analytical-coverage metrics.
- [ ] Screen the complete eligible universe continuously with production-grade provider coverage.
- [ ] Complete institutional reports, comparisons, screens, and watchlists across that full universe.

## Milestone 6 — Independent specialist committee

- [x] Replace weighted-voter authority with five independent specialists and the CIO.
- [x] Implement typed specialist contracts against the common candidate schema.
- [x] Enforce independent first-pass analysis.
- [x] Preserve the strongest dissent, disagreement reason, and resolving evidence.
- [x] Give Evidence & Governance explicit veto authority.
- [x] Give Portfolio & Risk explicit implementation-rejection authority.
- [x] Prevent specialists from issuing user-facing actions.
- [x] Prevent weighted averaging from manufacturing CIO action or confidence.

## Milestone 7 — Chief Investment Officer synthesis

- [x] Build deterministic, auditable CIO synthesis.
- [x] Compare expected return, downside, evidence quality, opportunity cost, and qualified alternatives.
- [x] Resolve disagreement without erasing dissent.
- [x] Apply evidence vetoes and implementation blocks.
- [x] Produce confidence from disclosed evidence and reliability rules.
- [x] Support Buy, Increase, Hold, Reduce, Exit, Watch, Insufficient evidence, No superior opportunity, and No material change.
- [x] Enforce abstention for inadequate evidence, stale inputs, unresolved disagreement, weak edge, infeasibility, or cost destruction.
- [x] Produce the approved thesis and plain-English explanation.

## Milestone 8 — Portfolio construction and implementation

- [x] Maintain point-in-time portfolio states and versioned constraints.
- [x] Determine position size, allocation, funding, and replacement separately from analytical confidence.
- [x] Enforce cash, position, sector, factor, correlation, liquidity, turnover, and cost controls.
- [x] Estimate transaction cost and slippage.
- [x] Allocate scarce capital in opportunity-rank order.
- [x] Roll back orphaned funding sales when an allocation is infeasible.
- [x] Persist and expose the complete non-executing construction result.
- [x] Record simulated paper fills for later implementation attribution.
- [ ] Add production rebalancing orchestration, order sequencing, and market-hours controls.
- [ ] Add a separately governed broker integration only after paper validation and explicit approval.

## Milestone 9 — Continuous thesis monitoring

- [x] Create an explicit living thesis for implemented ownership.
- [x] Persist original rationale, expected return, assumptions, catalysts, risks, invalidation conditions, evidence, and review timing.
- [x] Preserve immutable thesis snapshots rather than rewriting history.
- [x] Classify strengthening, stable, weakening, stale-evidence, replacement-opportunity, exit-review, and invalidated states.
- [x] Compare active ownership with qualified replacement opportunities.
- [x] Require CIO review before any action-oriented monitoring proposal.
- [ ] Complete production event-driven and scheduled monitoring across the full eligible universe.
- [ ] Validate alert usefulness and false-positive rates across extended live paper operation.

## Milestone 10 — Daily Capital Intelligence and product surfaces

- [x] Retain only Today, Environment, Portfolio, and History as primary navigation.
- [x] Make Today a concise CIO briefing rather than a news feed or score dashboard.
- [x] Answer what changed, why it matters, the opportunity or risk, whether the portfolio should change, confidence, and change conditions.
- [x] Show an honest no-decision state when the canonical journal has no governed result.
- [x] Keep Environment diagnostic and non-authoritative.
- [x] Show construction, costs, constraints, and paper activity at portfolio level.
- [x] Show point-in-time evaluations and living theses in History.
- [x] Remove Personal CIO, Investor Memory, conviction trend, and legacy recommendation fallbacks from active surfaces.
- [x] Expose canonical journal records through `/v1/cio/*`.

## Milestone 11 — Evaluation, attribution, and calibration

- [x] Freeze the exact decision-time evidence and original capital-alternative set.
- [x] Compare realized performance with cash, benchmark, passive portfolio, and the best original alternative.
- [x] Separate process quality from favorable or unfavorable outcome.
- [x] Attribute selection, sizing, timing, and implementation cost.
- [x] Add Brier score and confidence-calibration buckets.
- [x] Enforce ordered walk-forward windows.
- [x] Reject look-ahead inputs and survivorship-invalid securities.
- [x] Journal evaluations, calibration, walk-forward audits, and paper fills.
- [x] Prohibit automatic model-weight or governance changes from retrospective evaluation.
- [ ] Accumulate sufficient out-of-sample decisions across market regimes to support statistically credible product claims.
- [ ] Complete formal paper-trading governance review and release approval.

## Milestone 12 — Production data and operations

- [x] Authentication, role and mandate authorization, and query-only market/portfolio API access.
- [x] Selective material-change alerts and delivery preferences.
- [x] Hardened containers, dependency locks, CodeQL, dependency audit, image scan, backup, and restore controls.
- [x] Read-only canonical CIO journal API with content hashes.
- [x] Add security-master ingestion status, source-age monitoring, catalog and operation hash verification, and an activation gate.
- [ ] Expand licensed market, fundamentals, estimates, corporate-actions, and historical-universe coverage.
- [ ] Add production SLOs for provider freshness, full-universe cycle completion, thesis reviews, and evaluation latency.
- [ ] Complete long-duration incident, recovery, and data-reconciliation exercises at production scale.
- [ ] Obtain governance approval before enabling any real-money execution capability.

## Completion boundary

The core AI CIO decision architecture is complete when judged as software architecture: every recommendation follows the governing rule, uses point-in-time evidence, preserves authority boundaries, and supports abstention, audit, monitoring, and evaluation.

The product is not yet proven as a production investment manager. That separate boundary requires comprehensive live data, extended out-of-sample evidence, paper-trading validation across regimes, operational scale, governance review, and independently controlled execution.
