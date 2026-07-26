# Institutional Decision Engine

> This document implements the decision rules in [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md). The governing specification prevails over legacy recommendation, committee-consensus, Personal CIO, and investor-objective contracts.

## Objective

The decision engine identifies and selects the strongest evidence-supported use of capital in order to maximize expected long-term compounded portfolio return.

Risk, liquidity, concentration, drawdown, turnover, transaction costs, slippage, leverage, data quality, model confidence, and execution feasibility constrain the pursuit of return. Individual financial goals do not alter the objective or the investment process.

## Decision stages

```text
Point-in-time evidence
    -> structured signals and expected-return evidence
    -> candidate qualification and ranking
    -> five independent specialist analyses
    -> Evidence & Governance veto evaluation
    -> CIO synthesis and final action
    -> portfolio construction and implementation feasibility
    -> active thesis monitoring
    -> outcome evaluation and attribution
```

Each stage owns a distinct decision boundary. An analytical score cannot bypass opportunity qualification, specialist review, CIO authority, or portfolio implementation controls.

## Common candidate record

Every candidate must eventually provide a schema-versioned, point-in-time record containing:

- asset, asset class, listing, and recommendation-eligibility policy;
- current price and decision timestamp;
- decision horizon;
- base, bull, and bear expected returns;
- scenario probabilities and probability-weighted expected return;
- estimated fair value, expected upside, expected downside, and probability of success;
- catalysts, risks, critical assumptions, and invalidation conditions;
- supporting and contradictory evidence;
- evidence reliability, freshness, relevance, independence, completeness, and point-in-time integrity;
- data coverage and known limitations;
- liquidity, transaction costs, slippage, and implementation feasibility;
- opportunity cost and comparison with current holdings, cash, and qualified alternatives;
- expected portfolio contribution and constraint impact;
- five specialist analyses, material dissent, and veto status;
- CIO action, final confidence, approved thesis, recommended size, monitoring indicators, and review date;
- model, policy, schema, and code versions.

Categorical labels may summarize these values for users. They may not replace quantitative expected-return, downside, cost, and opportunity comparisons.

## Candidate qualification and ranking

A candidate may reach specialist review only when it meets versioned minimums for:

- Version 1 recommendation eligibility;
- expected return;
- evidence quality and independence;
- data freshness and analytical coverage;
- liquidity;
- cost-adjusted advantage;
- thesis clarity and falsifiability; and
- implementation feasibility.

Ranking must consider probability-weighted expected return, probability of success, downside severity, horizon, evidence quality and freshness, liquidity, costs, opportunity cost, portfolio contribution, thesis clarity, and invalidation clarity.

Conviction or a composite score alone may not determine ranking.

## Independent specialist process

The committee contains five specialists plus the CIO:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The five specialists complete independent first-pass analyses before seeing one another’s conclusions.

Each specialist output includes:

- conclusion within the specialist mandate;
- expected-return impact;
- supporting evidence;
- contradictory evidence;
- key assumptions;
- risks;
- confidence and limitations;
- observable conditions that would change the conclusion; and
- a structured position of supportive, neutral, opposed, abstain, or veto when authorized.

Specialists do not issue user-facing Buy, Increase, Hold, Reduce, or Exit actions.

## Specialist responsibilities

### Macro & Economic Strategist

Evaluates regime, inflation, monetary and fiscal policy, rates, credit, liquidity, employment, growth, currencies, commodities, and geopolitical risk.

### Market Strategist

Evaluates trend, momentum, relative strength, breadth, leadership, volume, volatility, positioning, short interest, flows, liquidity, and cross-asset confirmation.

### Fundamental & Valuation Analyst

Evaluates business quality, financial statements, growth, cash flow, margins, return on capital, balance-sheet quality, management execution, industry structure, revisions, valuation, fair value, and expected return.

### Portfolio & Risk Manager

Evaluates portfolio contribution, sizing, concentration, correlation, factor and sector exposure, drawdown, liquidity, cost, opportunity cost, funding, rebalancing, replacement candidates, and implementation feasibility.

This member may reject an implementation that violates portfolio constraints. An implementation block does not rewrite specialist evidence or manufacture a sell action.

### Evidence & Governance Officer

Evaluates source reliability, freshness, independence, completeness, consistency, conflict, model coverage, confidence justification, point-in-time integrity, schema completeness, reproducibility, compliance, and explainability.

This member may veto when evidence is inadequate, stale, materially conflicting, unsupported, incomplete, irreproducible, or paired with unjustified confidence.

## CIO synthesis

Only the Chief Investment Officer issues the final investment decision.

The CIO:

- reviews the five independent analyses;
- compares expected returns and downside across qualified alternatives;
- evaluates evidence strength, opportunity cost, and portfolio contribution;
- applies evidence vetoes and implementation blocks;
- preserves the strongest opposing conclusion and unresolved disagreement;
- determines whether the advantage is material after costs;
- selects the final action or disciplined abstention;
- approves the thesis and monitoring plan; and
- produces the user-facing explanation.

The objective is not consensus. Weighted vote aggregation and average specialist confidence may be retained only as disclosed supporting diagnostics. They may not become the final CIO action or overwrite material dissent.

## Permitted CIO outputs

- `buy`
- `increase`
- `hold`
- `reduce`
- `exit`
- `watch`
- `insufficient_evidence`
- `no_superior_opportunity`
- `no_material_change`

## Abstention and no-action standard

The CIO must abstain from an action recommendation when:

- evidence quality is below threshold;
- data is stale, incomplete, or irreproducible;
- expected return is below threshold;
- specialist disagreement is unresolved and material;
- liquidity is insufficient;
- costs or slippage eliminate the expected advantage;
- the candidate does not improve on a current holding or cash;
- expected portfolio improvement is immaterial;
- the thesis lacks testable assumptions or invalidation conditions; or
- no valid implementation satisfies portfolio constraints.

No action is a complete, terminal, reviewable decision. It records evidence, rationale, future action triggers, and review timing.

## Confidence

Confidence describes evidence strength and decision reliability. It does not guarantee a return.

Confidence must be derived from disclosed dimensions such as evidence reliability, independence, freshness, completeness, analytical coverage, conflict, model limitations, scenario robustness, and specialist agreement after preserving dissent.

Missing data lowers coverage and confidence. It does not default to neutral unless a versioned policy explicitly permits that treatment.

Confidence must later be calibrated against observed outcomes over a sufficient sample.

## Portfolio-construction boundary

The CIO determines what should be owned. The portfolio layer determines how much to own, what funds it, when implementation occurs, and how to minimize costs while enforcing constraints.

Position size is not a direct transform of a score or CIO confidence. It also depends on expected return, downside, volatility, liquidity, correlation, concentration, factor exposure, cash, turnover, cost, drawdown policy, and portfolio state.

Individual investor goals, retirement targets, preferred philosophies, and behavioral profiles are prohibited portfolio-optimization inputs.

## Thesis lifecycle

Approved decisions become append-only living theses with:

- original rationale and assumptions;
- expected return, downside, and horizon;
- catalysts and invalidation conditions;
- monitoring indicators and material-change triggers;
- initial and current confidence;
- current evidence and performance;
- next scheduled review; and
- strengthening, stable, weakening, reduced, exited, invalidated, and evaluated transitions.

Every active thesis must be compared with qualified alternatives and may not remain owned without current justification.

## Explainability and AI

AI may explain structured evidence, compare alternatives, identify contradictions, and render reports. It may not invent data, alter deterministic calculations, hide missing or conflicting evidence, create investor objectives, override a veto or implementation block, manufacture CIO authority, or generate unconstrained allocations.

All AI-generated prose must be traceable to structured inputs.

## Decision record and evaluation

Persist the complete input snapshot, evidence lineage, candidate record, specialist analyses, dissent, vetoes, CIO synthesis, final action, portfolio state, implementation result, model and policy versions, timestamps, and code release identifier.

Subsequent evaluation attaches realized outcomes without rewriting what was known at decision time.

Evaluation must distinguish process quality from outcome and attribute value creation or destruction to analysis, sizing, execution, timing, evidence, assumptions, and opportunity selection.

Model changes require point-in-time historical testing, out-of-sample validation, paper trading, comparison with the prior version, governance approval, versioning, rollback capability, and documented acceptance criteria.