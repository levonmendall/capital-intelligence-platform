# Capital Intelligence Platform Roadmap

> [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md) is the binding product and engineering contract. Roadmap items may refine sequencing but may not change the governing objective, committee authority, Version 1 universe, common decision schema, or abstention rules.

## Governing objective

> **Maximize long-term compounded portfolio returns.**

Risk, liquidity, concentration, drawdown, turnover, costs, leverage, evidence quality, data freshness, model confidence, and execution feasibility are constraints that protect compounding. Individual financial goals are not investment objectives and must not influence candidate ranking, specialist analysis, CIO decisions, or portfolio construction.

## Current release

Foundation 1.x provides a deployable and operationally hardened baseline with:

- point-in-time macro and market evidence;
- normalized provenance-aware data contracts;
- seven analytical engines;
- append-only institutional history and decision-quality reviews;
- committee and portfolio-fit foundations;
- continuous analysis with selective material-change alerts;
- a four-surface application and authenticated API;
- reproducible dependency and security controls; and
- encrypted, integrity-verified backups.

The foundation is valuable but the product is not yet a complete AI CIO. The immediate program is to realign the active product contract, then build the opportunity, specialist-analysis, CIO-synthesis, portfolio-construction, thesis-monitoring, and evaluation layers required by the governing specification.

## Milestone 1 — Governing product realignment

- [x] Adopt one objective: maximize long-term compounded portfolio returns.
- [x] Make the consolidated product and engineering specification authoritative.
- [ ] Remove investor goals, personal required return, retirement targets, preferred investment philosophy, and behavioral memory from the active decision path.
- [ ] Preserve historical personal-goal records only as isolated migration data until safely retired.
- [ ] Rename Personal CIO surfaces and APIs to Capital Intelligence CIO terminology.
- [ ] Replace objective-aware Portfolio Alignment with measurable Portfolio Contribution or Portfolio Improvement.
- [ ] Demote the Capital Intelligence Score from product identity to a supporting environment/evidence indicator.
- [ ] Add automated architecture tests preventing personal-goal inputs from entering ranking, committee, CIO, portfolio, alert, or explanation services.
- [ ] Add PR templates and tests enforcing the governing specification.

Acceptance: no active recommendation, ranking, committee, portfolio, alert, or user-facing decision depends on individual financial goals or personalized investment philosophies.

## Milestone 2 — Decision integrity and point-in-time evidence

Completed foundation:

- [x] Strict normalized observation and provenance models.
- [x] Publication, retrieval, vintage, and point-in-time availability fields.
- [x] Explicit live, cached, stale, fixture, fallback, and missing states.
- [x] Provider-neutral economic, security, filing, and market contracts.
- [x] SEC acceptance-time handling and amended-filing preservation.
- [x] FRED retrieval, caching, freshness, and stale-if-error disclosure.
- [x] Append-only institutional journal with hash-chain integrity.

Required completion:

- [ ] Persist complete release, revision, transformation, lineage, and provenance metadata for every recommendation input.
- [ ] Add evidence-origin grouping and derivative-source de-duplication.
- [ ] Add source hierarchy, reliability, freshness, relevance, independence, and completeness scoring.
- [ ] Add deterministic conflict-resolution and data-quality policies.
- [ ] Retrieve older SEC submission archives and dimensional XBRL metadata.
- [ ] Add licensed historical identifiers, corporate actions, and delisted securities.
- [ ] Define versioned price-adjustment and cross-venue consolidation policies.
- [ ] Add complete decision replay proving exactly what was known at decision time.

Acceptance: every candidate and CIO decision can be reproduced from its point-in-time evidence package without look-ahead data or duplicate-evidence inflation.

## Milestone 3 — Version 1 recommendation universe

Direct recommendation eligibility is limited to:

- liquid U.S.-listed equities;
- liquid U.S.-listed ETFs; and
- cash or short-duration Treasury equivalents.

- [ ] Add a versioned `RecommendationUniversePolicy`.
- [ ] Require U.S. listing, supported instrument type, minimum liquidity, data freshness, and analytical coverage.
- [ ] Distinguish intelligence-only assets from recommendation-eligible assets.
- [ ] Block crypto, commodities, currencies, options, individual bonds, international equities, and unvalidated instruments from direct CIO actions.
- [ ] Retain broader markets as evidence and regime inputs.
- [ ] Add tests proving unsupported asset classes cannot enter ranking, committee approval, sizing, or portfolio implementation.

Acceptance: architectural multi-asset support cannot be mistaken for direct recommendation authority.

## Milestone 4 — Common candidate decision schema

- [ ] Replace categorical expected-return/risk-only recommendation contracts with a comparable quantitative candidate record.
- [ ] Require current price and decision horizon.
- [ ] Require base, bull, and bear expected returns and scenario probabilities.
- [ ] Calculate probability-weighted expected return.
- [ ] Require fair value, upside, downside, and probability of success.
- [ ] Require catalysts, risks, assumptions, invalidation conditions, and monitoring indicators.
- [ ] Require supporting and contradictory evidence with quality and freshness.
- [ ] Require liquidity, costs, slippage, opportunity cost, and portfolio contribution.
- [ ] Preserve specialist conclusions and material dissent.
- [ ] Require final confidence, action, recommended size, and review date.
- [ ] Add schema versioning, serialization, point-in-time persistence, and replay tests.

Acceptance: every candidate is comparable, auditable, testable, and capable of disciplined abstention.

## Milestone 5 — Opportunity detection and ranking

- [ ] Build normalized company and financial-statement models.
- [ ] Add quality, financial strength, growth, earnings quality, valuation, momentum, regime-fit, and company-risk engines.
- [ ] Screen the complete eligible Version 1 universe.
- [ ] Detect improving and deteriorating candidates, dislocations, catalysts, regime beneficiaries, and weakening theses.
- [ ] Estimate expected return, downside, probability of success, evidence quality, liquidity, and costs.
- [ ] Compare candidates with current holdings, cash, and other qualified alternatives.
- [ ] Rank by probability-weighted expected return, downside, evidence, liquidity, costs, opportunity cost, and portfolio contribution.
- [ ] Reject weak, redundant, stale, illiquid, or infeasible candidates before committee review.
- [ ] Generate institutional stock and ETF reports, comparisons, rankings, screens, and watchlists.

Acceptance: committee attention is reserved for qualified candidates representing plausible superior uses of capital.

## Milestone 6 — Independent specialist committee

The committee contains five independent specialists plus the CIO:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

- [ ] Replace the legacy macro/risk/credit/liquidity/valuation/technical weighted-voter default.
- [ ] Implement typed specialist-analysis contracts against the common decision schema.
- [ ] Enforce independent first-pass analysis before conclusions are shared.
- [ ] Preserve majority conclusion, strongest dissent, disagreement reason, and evidence that could resolve it.
- [ ] Give the Evidence & Governance Officer explicit veto authority for inadequate or irreproducible evidence.
- [ ] Give the Portfolio & Risk Manager explicit implementation-rejection authority for constraint violations.
- [ ] Prevent specialists from issuing user-facing actions.
- [ ] Prevent weighted averaging from manufacturing a CIO decision or confidence value.

Acceptance: specialist outputs are independent analyses and only the CIO has final action authority.

## Milestone 7 — Chief Investment Officer synthesis

- [ ] Build a deterministic and auditable CIO synthesis service.
- [ ] Compare expected returns, downside, evidence quality, opportunity cost, and qualified alternatives.
- [ ] Resolve disagreement without erasing dissent.
- [ ] Apply Evidence Officer vetoes and portfolio implementation blocks.
- [ ] Produce final confidence from disclosed evidence and decision-reliability rules.
- [ ] Support Buy, Increase, Hold, Reduce, Exit, Watch, Insufficient evidence, No superior opportunity, and No material change.
- [ ] Enforce abstention for inadequate evidence, stale data, unresolved disagreement, low expected return, immaterial improvement, infeasible implementation, or costs that eliminate advantage.
- [ ] Produce the approved thesis and plain-English user explanation.

Acceptance: every user-facing investment action is attributable to the CIO and can explain why it is preferable to available alternatives or why no action is superior.

## Milestone 8 — Portfolio construction and implementation

Completed foundation:

- [x] Point-in-time portfolio snapshots, positions, proposals, asset buckets, and versioned mandate constraints.
- [x] Direction, liquidity, concentration, cash-reserve, risk-budget, and overlap fit checks.
- [x] Explicit non-executing opportunity-cost funding explanations.

Required completion:

- [ ] Maximize expected long-term compounded return subject to versioned constraints.
- [ ] Add position sizing, allocation optimization, funding decisions, and replacement logic.
- [ ] Add sector, factor, correlated-exposure, liquidity, turnover, leverage, and drawdown constraints.
- [ ] Add transaction-cost and slippage estimates.
- [ ] Add rebalancing orchestration and execution sequencing.
- [ ] Add paper-trading implementation behind approval and fit gates.
- [ ] Keep recommendation authority separate from sizing and execution authority.

Acceptance: an approved CIO decision becomes a feasible, cost-aware portfolio change or an explicit implementation abstention.

## Milestone 9 — Continuous thesis monitoring

- [x] Define append-only thesis concepts and falsification triggers.
- [ ] Implement Candidate, Under Review, Approved, Active, Strengthening, Stable, Weakening, Reduced, Exited, Invalidated, and Evaluated states.
- [ ] Persist original rationale, assumptions, expected return, horizon, catalysts, invalidation conditions, monitoring indicators, and initial confidence.
- [ ] Track current evidence, current confidence, performance, next review, and material-change triggers.
- [ ] Run event-driven and scheduled monitoring.
- [ ] Compare each active thesis with qualified replacement opportunities.
- [ ] Generate Increase, Hold, Reduce, Exit, or Continue monitoring proposals for CIO review.

Acceptance: every active position has a living, testable, point-in-time thesis and cannot remain owned without current justification.

## Milestone 10 — Daily Capital Intelligence

- [x] Maintain Today, Environment, Portfolio, and History as the four primary surfaces.
- [x] Keep continuous analysis separate from selective notifications.
- [ ] Replace score-first opening hierarchy with one coherent CIO briefing.
- [ ] Surface only material opportunity, risk, and thesis changes.
- [ ] Explain whether the portfolio should change, the CIO action, confidence, and what would change the conclusion.
- [ ] Hide internal committee mechanics by default while preserving drill-down auditability.
- [ ] Remove investor-goal onboarding and goal-derived alert wording.
- [ ] Keep No material change and No action required as first-class daily outcomes.

Acceptance: the interface communicates judgment rather than information volume or internal process theater.

## Milestone 11 — Evaluation, attribution, and controlled learning

- [x] Separate process quality from realized outcome.
- [x] Persist append-only decision-quality reviews.
- [ ] Add walk-forward backtests with point-in-time fundamentals and survivorship controls.
- [ ] Model transaction costs, slippage, turnover, and implementation delay.
- [ ] Compare with a broad market benchmark, cash, passive reference portfolio, prior system versions, and the contemporaneous opportunity set.
- [ ] Track CAGR, compounded return, drawdown, hit rate, capture ratios, costs, and opportunity cost.
- [ ] Attribute value creation or destruction to analysis, sizing, execution, timing, committee signals, evidence types, sources, and assumptions.
- [ ] Calibrate confidence against observed outcomes over sufficient samples.
- [ ] Require historical, out-of-sample, and paper-trading validation plus governance approval and rollback for model changes.
- [ ] Prohibit autonomous process rewriting from short-term results.

Acceptance: the platform can determine not only what happened, but why the decision process created or destroyed value.

## Explicitly out of scope for Version 1

- Individual financial-goal optimization
- Retirement planning
- Behavioral coaching
- Personalized investment philosophies
- Social investing
- News-feed experiences
- High-frequency trading
- Unvalidated alternative-data recommendations
- Direct recommendations across every asset class
- Autonomous model self-modification
- Excessive exposure of committee mechanics
- Live brokerage execution before paper validation and explicit operational approval

## Definition of product completion

Capital Intelligence Version 1 is complete only when it can continuously identify qualified opportunities in the eligible universe, compare them with current uses of capital, obtain five independent specialist analyses, issue one auditable CIO decision, construct a feasible portfolio response, monitor the resulting thesis, and measure whether the decision improved long-term compounded return.