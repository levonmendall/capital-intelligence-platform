# Capital Intelligence — Consolidated Product and Engineering Specification

## Authority

This document is the binding product and engineering specification for Capital Intelligence. It supersedes conflicting language in older roadmap, product, Personal CIO, investor-goal, asset-scope, committee-consensus, recommendation, and interface documents.

When implementation or documentation conflicts with this specification, this specification governs. Compatibility code may remain temporarily only when it is isolated from recommendation, ranking, committee, portfolio-construction, monitoring, and user-facing CIO decisions and has an explicit removal plan.

## Executive Summary

Capital Intelligence is an AI Chief Investment Officer designed to maximize long-term compounded portfolio returns through continuous, objective, and evidence-based investment decision-making.

The platform is not a financial planner, goal-based robo-advisor, trading-signal service, or financial news application. It applies one disciplined institutional investment process to identify the strongest available uses of capital.

The platform continuously:

1. Observes the global financial system.
2. Converts raw information into structured evidence.
3. Detects and ranks investment opportunities.
4. Evaluates candidates through independent investment disciplines.
5. Produces a final Chief Investment Officer decision.
6. Constructs and updates the portfolio.
7. Monitors every active investment thesis.
8. Evaluates outcomes and improves the decision process.

The system has one governing objective:

> **Maximize long-term compounded portfolio returns.**

Risk, liquidity, concentration, transaction costs, execution feasibility, data quality, and capital preservation are operating constraints that protect the compounding process. They are not competing investor goals.

---

# 1. Product Vision

Capital Intelligence continuously analyzes the world’s financial system, separates signal from noise, identifies the strongest evidence-supported investment opportunities, and transforms institutional-quality analysis into disciplined portfolio decisions.

The platform should feel like a world-class Chief Investment Officer working continuously on behalf of the portfolio.

It should answer five questions:

1. What changed?
2. Why does it matter?
3. What investment opportunity or risk has emerged?
4. Should the portfolio change?
5. How confident is the decision?

The purpose is not to provide more information.

The purpose is to make better capital-allocation decisions.

---

# 2. North Star

> **Capital Intelligence is an AI Chief Investment Officer designed to maximize long-term compounded portfolio returns by continuously identifying, evaluating, implementing, and monitoring the strongest evidence-supported uses of capital.**

Every feature, model, data source, interface, and recommendation should be evaluated against one question:

> **Does this improve the platform’s ability to compound capital over the long term?**

If the answer is no, the feature does not belong in the core product.

---

# 3. Objective Function

## Primary Objective

Maximize expected long-term compounded portfolio return.

The preferred long-term measurement is portfolio CAGR, supported by shorter-horizon expected-return estimates.

## Operating Constraints

The system must pursue return within explicit constraints:

* Maximum position size
* Maximum sector exposure
* Maximum factor exposure
* Maximum correlated exposure
* Liquidity requirements
* Transaction costs
* Slippage
* Turnover limits
* Leverage policy
* Evidence-quality thresholds
* Drawdown and permanent-capital-loss limits
* Execution feasibility
* Data freshness
* Model confidence

These constraints exist to prevent the platform from pursuing fragile or unsustainable returns.

## Supporting Metrics

Risk-adjusted measures remain useful diagnostic tools, but they are not the system’s primary objective.

Supporting metrics may include:

* Sharpe ratio
* Sortino ratio
* Maximum drawdown
* Volatility
* Upside capture
* Downside capture
* Hit rate
* Return relative to benchmark
* Return relative to cash
* Opportunity cost
* Turnover-adjusted return

---

# 4. Scope and Investment Universe

## One Portfolio and All-Market Analysis

The platform operates one active paper portfolio:

* Portfolio code: `COMPOUNDING`
* Initial paper capital: **$250,000**
* Base currency: USD
* Objective: maximize long-term compounded returns after implementation costs and within approved constraints

The platform must continuously analyze all supported liquid public-market families, including:

* Global equities and listed funds
* Government bonds and credit
* Cash equivalents
* Commodities and precious metals
* Foreign exchange
* Crypto
* Real-estate securities
* Options and volatility markets
* Other liquid alternatives

The analysis universe must be built from a provider-driven, point-in-time security master. A static shortlist cannot define the active opportunity set.

## Governed Direct Allocation

All-market analysis is mandatory; direct allocation is conditional. An instrument may become a direct paper recommendation target only when the complete point-in-time capability stack is approved: identity, licensed data, valuation, expected return, liquidity, risk, transaction costs, execution, custody, settlement, thesis monitoring, outcome evaluation, and governance lineage.

An unavailable or unapproved capability keeps the market evidence-only, research-only, or ineligible. It must never be treated as absent evidence for the purpose of claiming that the remaining market is the best use of capital.

Each newly eligible asset class remains under the same `COMPOUNDING` objective. It cannot create a separate crypto, global, income, defensive, growth, or tactical portfolio.

---

# 5. Organizational Architecture

```text
Global Financial Intelligence
        │
        ▼
Data Normalization, Provenance
and Point-in-Time Storage
        │
        ▼
Signal and Evidence Generation
        │
        ▼
Opportunity Detection and Ranking
        │
        ▼
Independent Specialist Analysis
        │
        ▼
Chief Investment Officer Decision
        │
        ▼
Portfolio Construction and Implementation
        │
        ▼
Continuous Thesis Monitoring
        │
        ▼
Daily Capital Intelligence
        │
        ▼
Decision Evaluation, Attribution
and Confidence Calibration
        │
        └──────── Validated feedback into models
```

The system should be understood as a continuous decision loop rather than a linear reporting pipeline.

---

# 6. Layer 1 — Global Financial Intelligence

The platform continuously collects financial, economic, corporate, market, and event information.

Data should be organized by the type of understanding it creates rather than by vendor or feed.

## 6.1 Macroeconomic Intelligence

Monitor inflation, interest rates, central-bank policy, GDP and economic growth, employment, wages, fiscal policy, government spending, money supply, global liquidity, the Treasury yield curve, credit spreads, lending conditions, commodity prices, currency markets, and geopolitical developments.

Purpose: determine the economic regime and identify conditions that create or destroy return opportunities.

## 6.2 Market Intelligence

Monitor price action, momentum, trend, market breadth, relative strength, sector and industry leadership, volume, volatility, ETF and mutual-fund flows, institutional positioning, options positioning, short interest, cross-asset relationships, and liquidity conditions.

Purpose: understand what markets are communicating through price, positioning, liquidity, and participation.

## 6.3 Fundamental and Valuation Intelligence

Monitor financial statements, revenue growth, earnings, cash flow, margins, return on invested capital, balance-sheet strength, capital allocation, repurchases, dividends, mergers and acquisitions, insider transactions, guidance revisions, analyst estimate revisions, competitive advantages, management execution, industry structure, valuation, and unit economics.

Purpose: estimate business quality, intrinsic value, and expected investment return.

## 6.4 Capital-Flow Intelligence

Monitor capital movement across equities, bonds, cash, sectors, industries, ETFs, fixed-income categories, commodities, precious metals, international markets, investment styles, and market-cap segments.

Purpose: identify changes in capital allocation and market leadership before they are fully reflected in prices.

## 6.5 Event Intelligence

Every material event should be evaluated through an expectations-versus-reality framework. The system must determine what was expected, what occurred, the size of the surprise, why the market reacted, whether the reaction was justified, whether expected return changed, and whether an existing thesis was strengthened or invalidated.

Events include economic releases, central-bank decisions, earnings, guidance changes, regulatory actions, mergers, credit events, corporate actions, geopolitical developments, management changes, and product announcements.

Purpose: transform events and news into structured investment evidence.

## 6.6 Structural Intelligence

Monitor long-term economic and industry developments such as artificial intelligence, robotics, semiconductors, cybersecurity, electrification, defense spending, healthcare innovation, energy and water infrastructure, reshoring, demographic change, industrial automation, and data-center development.

Structural themes must be supported by measurable evidence such as revenue exposure, capital expenditure, adoption rates, unit economics, market-share changes, capacity constraints, pricing power, earnings revisions, cash-flow impact, and valuation relative to expected growth.

Structural themes generate candidates. They do not independently generate recommendations.

## 6.7 Correlation Intelligence

Continuously analyze relationships between assets, sectors, factors, and economic variables. Correlations must be allowed to vary across regimes rather than treated as permanently stable.

Purpose: understand how changing relationships affect portfolio exposures.

## 6.8 Historical Intelligence

Compare current conditions with historical environments across macro regime, valuation, monetary and fiscal policy, positioning, credit, inflation, liquidity, leadership, and subsequent outcomes.

Historical analogs provide context and scenario ranges. They must not be deterministic forecasts, and the system must explain both similarities and material differences.

---

# 7. Data-Scope Priorities

## Tier 1 — Required

Prices, volume, corporate actions, financial statements, earnings, guidance, regulatory filings, economic releases, interest rates, Treasury curve, credit spreads, consensus expectations, analyst revisions, portfolio holdings, and benchmark data.

Tier 1 data is required for dependable recommendations.

## Tier 2 — Advanced

Fund flows, options positioning, short interest, institutional ownership, industry indicators, supply-chain information, cross-asset signals, historical analogs, and alternative valuation inputs.

Tier 2 strengthens analysis but should not be required for every decision.

## Tier 3 — Experimental

Social sentiment, search activity, web traffic, satellite data, geospatial data, consumer transaction data, and other alternative datasets.

Tier 3 evidence must never independently trigger a recommendation until its incremental predictive and explanatory value has been validated.

---

# 8. Layer 2 — Data Normalization, Provenance and Point-in-Time Storage

All information must be normalized before entering the decision system.

Responsibilities include standardizing identifiers, units, and currencies; resolving conflicts; tracking original sources, publication time, ingestion time, revision history, transformations, freshness, missing data, and duplicates; and preserving point-in-time snapshots.

Every recommendation must preserve exactly what the platform knew when the decision was made, including available data, sources, timestamps, revisions, model versions, committee outputs, portfolio state, market price, confidence calculation, supporting evidence, and contradictory evidence.

This is required for decision replay, backtesting, auditability, reproducibility, evaluation, and look-ahead-bias prevention.

---

# 9. Source Hierarchy and Evidence Independence

The platform must distinguish original evidence from repeated reporting.

Preferred hierarchy:

1. Regulatory filings and official releases
2. Exchanges, central banks, and government agencies
3. Company disclosures
4. Established institutional data providers
5. Reputable financial reporting
6. Commentary, sentiment, and secondary interpretation

The system must identify originating sources, group derivative reports, de-duplicate repeated evidence, detect conflicts, assign reliability, freshness, and relevance scores, track evidence independence, penalize incomplete coverage, and distinguish facts from interpretations.

Recommendation confidence must not rise simply because the same underlying event appears in multiple secondary sources.

---

# 10. Layer 3 — Signal and Evidence Generation

The Investment Intelligence Engine transforms normalized data into structured evidence.

Responsibilities include detecting material changes; calculating regimes and valuation changes; detecting fundamental improvement or deterioration; measuring expectations versus outcomes; identifying flows, correlation changes, structural trends, and historical context; calculating evidence quality; identifying conflict; estimating expected return and downside; and generating evidence packages.

The output is not a recommendation. It is structured evidence suitable for screening and committee evaluation.

---

# 11. Layer 4 — Opportunity Detection and Ranking

The system requires a formal mechanism for deciding what deserves committee attention.

Responsibilities include screening the investable universe; identifying improving and deteriorating assets; detecting valuation dislocations, regime beneficiaries, catalysts, and weakening theses; comparing candidates with current holdings; estimating expected and probability-weighted return and downside; evaluating opportunity cost; ranking candidates; and rejecting weak or redundant candidates.

A candidate reaches the committee only when minimum expected-return, evidence-quality, liquidity, freshness, analytical-coverage, and implementation-feasibility requirements are met.

---

# 12. Common Decision Schema

Every candidate must use the same structured decision record.

Required fields:

* Asset
* Asset class
* Current price
* Decision horizon
* Base-case expected return
* Bull-case expected return
* Bear-case expected return
* Probability-weighted expected return
* Estimated fair value
* Expected upside
* Expected downside
* Probability of success
* Primary catalysts
* Key risks
* Critical assumptions
* Thesis invalidation conditions
* Supporting evidence
* Contradictory evidence
* Evidence quality
* Evidence freshness
* Liquidity
* Transaction costs
* Opportunity cost
* Portfolio contribution
* Committee conclusions
* Documented disagreements
* Final confidence
* Recommended action
* Recommended position size
* Monitoring indicators
* Review date

This schema gives the CIO comparable inputs and makes every decision auditable and testable.

---

# 13. Layer 5 — Independent Specialist Analysis

The Investment Committee contains six participants:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five perform independent analysis. The Chief Investment Officer chairs the process and issues the final decision. There is no separate investor-goals member. The platform applies one investment objective across all portfolios.

---

# 14. Committee Member Goals and Responsibilities

## Macro & Economic Strategist

Mission: determine how the economic environment affects expected investment returns.

Evaluate economic regime, inflation, monetary policy, rates, fiscal policy, credit, liquidity, employment, growth, currencies, commodities, and geopolitical risk. Output regime classification, tailwinds, headwinds, systemic risks, scenarios, and candidate impact.

Primary question: **How does the current economic environment affect this opportunity’s expected return?**

## Market Strategist

Mission: determine what market behavior, positioning, and liquidity imply about the opportunity.

Evaluate trend, momentum, relative strength, breadth, leadership, volume, volatility, positioning, short interest, flows, liquidity, and cross-asset confirmation. Output market regime, technical condition, positioning, liquidity, entry conditions, and market risks.

Primary question: **What are price, positioning, participation, and liquidity communicating?**

## Fundamental & Valuation Analyst

Mission: determine intrinsic quality, fair value, and expected return.

For equities and equity ETFs, evaluate revenue, earnings, cash flow, margins, return on capital, balance-sheet quality, management execution, competitive advantages, capital allocation, industry structure, valuation, revisions, and long-term growth. Output quality, fair-value and expected-return ranges, catalysts, risks, assumptions, and invalidation conditions.

Primary question: **Does this asset offer an attractive expected return relative to its price and fundamental outlook?**

## Portfolio & Risk Manager

Mission: determine whether the candidate is the best available use of portfolio capital.

Evaluate portfolio contribution, sizing, concentration, correlation, sector and factor exposure, drawdown risk, liquidity, scenarios, opportunity cost, transaction costs, rebalancing impact, and replacement candidates. Output portfolio impact, recommended allocation, funding source, size limits, violations, and expected contribution.

Primary question: **Does this represent a superior deployment of portfolio capital under the system’s constraints?**

## Evidence & Governance Officer

Mission: protect integrity, reproducibility, and defensibility.

Validate source reliability, freshness, independence, completeness, consistency, contradictory evidence, model coverage, confidence, point-in-time integrity, decision-schema completeness, compliance, and explainability.

The Evidence & Governance Officer may veto when evidence is insufficient, data is stale, sources conflict materially, a decision cannot be reproduced, assumptions are unsupported, required coverage is missing, or confidence is unjustifiably high.

Primary question: **Can this decision be objectively defended and reproduced using the evidence available at the time?**

## Chief Investment Officer

Mission: select the strongest available use of capital based on all specialist analyses.

The CIO does not duplicate specialist research. It reviews independent assessments, compares expected returns, evaluates downside and opportunity cost, resolves disagreements, preserves dissent, determines final confidence, approves or rejects candidates, selects the final action, approves the thesis, produces the user explanation, and determines whether no action is preferable.

Primary question: **Given all available evidence and alternatives, what is the best use of capital?**

---

# 15. Committee Operating Rules

Each specialist completes an initial assessment before reviewing other conclusions. Evidence is scored for reliability, freshness, relevance, independence, and completeness. Disagreement is not averaged away. The CIO receives the majority conclusion, strongest opposing conclusion, reason for disagreement, and evidence that could resolve it.

Specialists issue analyses, not user-facing recommendations. The Evidence Officer may veto inadequate evidence. The Portfolio Manager may reject implementations that violate constraints. Only the CIO may issue the final investment decision.

The objective is not consensus. The objective is the strongest defensible capital-allocation decision.

---

# 16. Recommendation Ranking

Candidates must be ranked using expected return, probability of success, downside severity, horizon, evidence quality and freshness, liquidity, transaction costs, opportunity cost, portfolio contribution, thesis clarity, and invalidation clarity.

The governing question is:

> **Does this candidate represent the strongest available use of capital after accounting for expected return, downside, evidence quality, implementation costs, and opportunity cost?**

---

# 17. Permitted Decision Outputs

The CIO may issue Buy, Increase, Hold, Reduce, Exit, Watch, Insufficient evidence, No superior opportunity, No material change.

The platform should be comfortable recommending no action. No recommendation is preferable to a weak recommendation.

---

# 18. Abstention Rules

Do not issue an action recommendation when evidence quality is below threshold; expected return is below threshold; data is stale or incomplete; specialist disagreement is unresolved; liquidity is insufficient; costs eliminate the advantage; the candidate does not improve on an existing holding; improvement is immaterial; the thesis cannot be expressed through testable assumptions; or no valid implementation satisfies constraints.

Abstention is a valid and often preferable CIO decision.

---

# 19. Layer 6 — Chief Investment Officer Decision

Every approved decision includes action, asset, expected return, horizon, position size, thesis, supporting and contradictory evidence, assumptions, catalysts, risks, invalidation conditions, portfolio impact, opportunity cost, confidence, review date, and a plain-English explanation.

Confidence describes evidence strength and decision reliability. It is not a guarantee of future return.

---

# 20. Layer 7 — Portfolio Construction and Implementation

The Portfolio Construction Engine converts approved CIO decisions into an executable portfolio with the objective of maximizing expected long-term compounded portfolio return.

Responsibilities include sizing, allocation optimization, funding, rebalancing, exposure and correlation management, concentration, liquidity planning, turnover, cost and slippage estimation, sequencing, and constraint enforcement.

Required constraints include position, sector, factor and correlated-exposure limits; liquidity; turnover; leverage; evidence thresholds; drawdown; costs; and feasibility.

The CIO determines what should be owned. Portfolio Construction determines how much, what funds it, when implementation occurs, and how costs are minimized. Portfolio awareness remains essential. Individual financial goals do not influence the investment process.

---

# 21. Layer 8 — Continuous Thesis Monitoring

Every approved decision becomes a living investment thesis.

```text
Candidate
    ↓
Under Review
    ↓
Approved
    ↓
Active
    ↓
Strengthening / Stable / Weakening
    ↓
Reduced / Exited / Invalidated
    ↓
Evaluated
```

Required fields include original rationale, assumptions, expected return and timeline, catalysts, invalidation conditions, monitoring indicators, initial and current confidence, current evidence, performance since approval, next review, and material-change triggers.

Monitoring continuously asks why the position is owned, whether assumptions or expected return changed, whether downside increased, whether a superior opportunity emerged, whether the thesis still holds, and whether to increase, reduce, hold, or exit. Monitoring is event-driven and scheduled.

---

# 22. Layer 9 — Daily Capital Intelligence

The user experience presents one coherent CIO briefing rather than exposing internal committee mechanics.

The briefing answers what changed, why it matters, which opportunities improved, which risks increased, which active theses strengthened or weakened, whether the portfolio should change, what action is recommended, confidence, and what evidence would change the conclusion.

The default experience surfaces only material developments. Valid outcomes include no material change, no action required, continue monitoring, new opportunity, thesis strengthening, thesis weakening, and portfolio action recommended.

Complexity belongs inside the system. Clarity belongs in the interface.

---

# 23. Layer 10 — Decision Evaluation and Learning

The platform must evaluate whether decisions improved returns.

Track compounded return, CAGR, returns relative to benchmark, cash, and passive portfolios, drawdown, hit rate, capture ratios, turnover, costs, slippage, performance by recommendation, horizon, committee signal, and evidence domain, opportunity cost, thesis-failure reasons, and confidence calibration.

Attribution determines which decisions, signals, sources, evidence types, and assumptions created or destroyed value and whether poor results came from analysis, sizing, execution, or timing.

Confidence must be measurable and calibrated rather than rhetorical.

The platform must not autonomously rewrite its process based on short-term performance. Model changes require historical and point-in-time validation, out-of-sample testing, paper trading, comparison with prior versions, governance approval, and rollback capability.

---

# 24. Benchmarking

The objective remains absolute compounded return. Benchmarks are evaluation tools, not optimization targets.

Evaluate against a broad market benchmark, cash or risk-free return, a passive reference portfolio, previous system versions, and the opportunity set available at the time.

---

# 25. Explainability and Auditability

Every recommendation must be explainable at user, analytical, and audit levels.

The user explanation states what changed, why it matters, the recommended action, why it is preferable, and what could invalidate it.

The analytical explanation includes expected-return calculation, supporting and contradictory evidence, specialist conclusions, portfolio impact, opportunity cost, and confidence calculation.

The audit record includes the data snapshot, source provenance, model versions, specialist outputs, CIO decision, portfolio state, implementation details, thesis changes, and final outcome.

The platform must always answer:

> **What did we know, what did we believe, what did we do, and what happened afterward?**

---

# 26. Engineering Principles

Every feature must improve capital-allocation decisions; support long-term compounding; reduce cognitive load; use traceable evidence; preserve point-in-time integrity; support reproducibility; integrate with the common decision schema; strengthen monitoring or evaluation; avoid unnecessary interface complexity; permit no-action outcomes; and remain measurable and testable.

Prefer judgment over information volume, primary evidence over commentary, expected value over narrative conviction, reproducibility over opaque intelligence, continuous monitoring over isolated recommendations, and focused analytical depth over premature asset-class expansion.

---

# 27. Version 1 Implementation Priorities

1. Decision integrity: point-in-time storage, provenance, evidence de-duplication, source hierarchy, common schema, and reproducible records.
2. Opportunity process: screening, candidate generation, expected-return estimates, ranking, opportunity cost, and abstention.
3. Committee process: independent specialist outputs, Evidence Officer veto, portfolio checks, CIO synthesis, dissent, and final confidence.
4. Portfolio implementation: sizing, optimization, rebalancing, costs, exposure limits, and liquidity.
5. Thesis monitoring: states, assumptions, invalidation triggers, review schedules, confidence changes, and action updates.
6. Evaluation: attribution, benchmarks, confidence calibration, model-version comparison, and paper-trading validation.

---

# 28. Out of Scope for the Initial Version

The following are not first-class priorities: individual financial-goal optimization, retirement planning, behavioral coaching, personalized investment philosophies, social investing, news-feed experiences, high-frequency trading, unvalidated alternative-data signals, direct recommendations across every asset class, autonomous model self-modification, and excessive exposure of committee mechanics.

These capabilities can be considered later only when they reinforce the central objective.

---

# 29. Final Product Positioning

Capital Intelligence is not another financial information platform. It is a continuous institutional investment process.

The platform observes the global financial system, converts information into evidence, identifies the strongest available opportunities, evaluates them through independent investment disciplines, allocates portfolio capital, monitors every thesis, and measures whether decisions created value.

The defining promise is:

> **Capital Intelligence continuously determines the strongest evidence-supported use of capital and communicates that decision with clarity, discipline, and accountability.**

The platform should not attempt to prove how much information it can process. It should prove that it can make better, more explainable, and more accountable investment decisions over time.

---

# Enforcement Contract

Every pull request must answer the following:

1. Objective: does the change improve long-term capital compounding?
2. Universe: are direct recommendation targets eligible for Version 1?
3. Evidence: is the decision point-in-time, traceable, independent, and reproducible?
4. Opportunity: was the candidate compared with current holdings, cash, and qualified alternatives?
5. Committee: did the five specialists analyze independently before CIO synthesis?
6. Authority: was the final action issued only by the CIO?
7. Abstention: can the system return no action, no superior opportunity, or insufficient evidence?
8. Implementation: do size and funding satisfy constraints and costs?
9. Monitoring: does an approved decision become a falsifiable living thesis?
10. Evaluation: can the system determine whether analysis, sizing, execution, or timing created or destroyed value?

A change that violates these rules must not be merged into the core product.