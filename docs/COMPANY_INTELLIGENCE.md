# Company Intelligence Foundation

The `company` package translates accepted SEC company facts, point-in-time market data, and regime context into structured company evidence and the canonical CIO candidate schema.

It does not issue an investment action. Its output must still pass Version 1 universe policy, opportunity qualification and ranking, six independent specialist analyses, CIO synthesis, portfolio construction, and thesis monitoring.

## Point-in-time financial normalization

`CompanyFactNormalizer` consumes canonical `data.filing.CompanyFact` values and a timezone-aware decision timestamp.

It:

- excludes facts accepted after the decision time;
- accepts annual filing forms only;
- distinguishes annual-duration facts from balance-sheet instant facts;
- maps multiple XBRL tags to canonical financial metrics using disclosed preference order;
- lets the latest accepted amendment available at the decision time supersede the original value;
- preserves accession numbers and source-fact identifiers;
- groups overlapping debt concepts and selects at most one preferred fact per debt component to prevent double counting;
- leaves unavailable metrics as `None`; and
- requires actual revenue evidence before creating an annual statement.

Normalized annual periods preserve revenue, operating income, net income, operating cash flow, capital expenditures, assets, liabilities, equity, cash, debt, current assets and liabilities, and diluted shares when available.

Derived metrics include free cash flow, margins, current ratio, debt-to-assets, cash-to-debt, invested capital, return on invested capital, coverage, growth, and historical variability. Missing components never become zero or neutral automatically.

## Eight company factors

`CompanyAnalysisEngine` publishes exactly eight typed assessments:

1. Quality
2. Financial strength
3. Growth
4. Earnings quality
5. Valuation
6. Momentum
7. Regime fit
8. Company risk

Each assessment contains a bounded score, confidence, disclosed metrics, evidence text, risks, and methodology version.

### Quality

Uses return on invested capital, operating margin, free-cash-flow margin, and net margin.

### Financial strength

Uses debt-to-assets, current ratio, cash-to-debt, and equity-to-assets.

### Growth

Uses revenue, operating-income, net-income, and free-cash-flow CAGR when point-in-time history supports them.

### Earnings quality

Uses operating-cash-flow conversion, free-cash-flow conversion, and accruals relative to assets.

### Valuation

Uses earnings yield, free-cash-flow yield, sales yield, and dividend yield against disclosed versioned reference levels.

### Momentum

Uses six- and twelve-month return, benchmark-relative return, and price relative to the 200-day trend.

### Regime fit

Maps growth, liquidity, credit, and market-risk support through disclosed industry cyclicality and duration sensitivity.

### Company risk

Uses leverage, volatility, drawdown, revenue variability, and margin variability. Higher scores mean stronger risk characteristics rather than more risk.

The initial factor formulas are deterministic hypotheses, not validated constants. They require walk-forward and out-of-sample calibration before real-money reliance.

## Evidence quality

The company analysis publishes canonical evidence-quality dimensions. Point-in-time integrity remains explicit, market staleness reduces freshness, and financial and factor coverage reduce completeness. Independence is not assumed to be perfect merely because many derived metrics exist from the same underlying filings.

## Expected-return candidate

`CompanyCandidateBuilder` converts the company analysis into `CandidateDecisionRecord`.

The versioned expected-return policy combines:

- available earnings or free-cash-flow yield;
- dividend yield;
- bounded sustainable revenue growth;
- disclosed quality, growth, valuation, momentum, regime-fit, and company-risk adjustments; and
- market volatility and drawdown for bull and bear scenario spreads.

The output contains base, bull, and bear returns, fixed disclosed scenario probabilities, probability of success, fair value, supporting and contradictory evidence, liquidity, costs, opportunity cost, expected portfolio contribution, assumptions, invalidation conditions, monitoring indicators, evidence lineage, and model versions.

The expected-return mapping is an explicit versioned hypothesis. It is included in critical assumptions and must be calibrated through point-in-time historical testing, paper trading, and comparison with prior versions.

## Boundaries

- SEC normalization cannot infer missing facts.
- Company factor scores cannot issue actions or sizes.
- The candidate builder cannot bypass the Opportunity Engine.
- The Opportunity Engine recalculates opportunity cost from the current opportunity set.
- Specialists independently review qualified candidates.
- Only the CIO issues the final action.
- Portfolio construction determines feasible size and funding.
- Every approved ownership decision becomes a living thesis.
