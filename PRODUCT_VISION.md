# Capital Intelligence Product Vision

> This document summarizes the binding rules in [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md). The governing specification prevails whenever older documentation, compatibility code, or product language conflicts with it.

## North Star

> **Capital Intelligence is an AI Chief Investment Officer designed to maximize long-term compounded portfolio returns by continuously identifying, evaluating, implementing, and monitoring the strongest evidence-supported uses of capital.**

The product applies one disciplined institutional investment process. It is not a financial planner, goal-based robo-advisor, personalized investment-philosophy product, trading-signal service, or financial news application.

Risk, liquidity, concentration, transaction costs, slippage, turnover, leverage, drawdown, data quality, model confidence, and execution feasibility are constraints that protect compounding. They are not competing investor objectives.

## Product promise

The system continuously answers:

1. What changed?
2. Why does it matter?
3. What investment opportunity or risk emerged?
4. Should the portfolio change?
5. How confident is the decision?

The purpose is not to process or display more information. The purpose is to make better capital-allocation decisions.

## Version 1 recommendation universe

Capital Intelligence may directly recommend and allocate only among:

- liquid U.S.-listed equities;
- liquid U.S.-listed ETFs; and
- cash or short-duration Treasury equivalents.

Government bonds, credit, commodities, currencies, options, international markets, crypto, volatility, and other markets may inform intelligence. They are not direct recommendation targets until dedicated asset-specific valuation, return, risk, liquidity, implementation, and validation frameworks are approved.

The generalized multi-asset identity and evidence architecture remains valuable. Architectural support does not imply recommendation eligibility.

## Continuous decision loop

```text
Global Financial Intelligence
        -> Point-in-Time Data and Provenance
        -> Signal and Evidence Generation
        -> Opportunity Detection and Ranking
        -> Five Independent Specialist Analyses
        -> Chief Investment Officer Decision
        -> Portfolio Construction and Implementation
        -> Continuous Thesis Monitoring
        -> Daily Capital Intelligence
        -> Evaluation, Attribution, and Calibration
        -> validated feedback into versioned models
```

## Committee authority

The committee has six participants:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five independently analyze the same candidate before seeing one another’s conclusions. Specialists issue analyses, not user-facing actions. The Evidence & Governance Officer can veto inadequate or irreproducible evidence. The Portfolio & Risk Manager can reject implementations that violate constraints. Only the CIO issues the final investment decision.

The objective is not weighted consensus. It is the strongest defensible capital-allocation decision. Material dissent must be preserved rather than averaged away.

## Candidate and decision standard

Every candidate uses one comparable decision schema containing current price, horizon, base/bull/bear return estimates, scenario probabilities, probability-weighted expected return, fair value, upside, downside, probability of success, catalysts, risks, assumptions, invalidation conditions, evidence quality and freshness, liquidity, costs, opportunity cost, portfolio contribution, specialist conclusions, dissent, final confidence, action, size, monitoring indicators, and review date.

Candidates reach committee review only when minimum expected-return, evidence-quality, freshness, liquidity, analytical-coverage, and implementation-feasibility requirements are satisfied.

Permitted CIO outputs are:

- Buy
- Increase
- Hold
- Reduce
- Exit
- Watch
- Insufficient evidence
- No superior opportunity
- No material change

No action is preferable to a weak action.

## Portfolio construction boundary

The CIO determines what should be owned. The Portfolio Construction Engine determines how much to own, what funds it, when implementation occurs, and how to minimize unnecessary cost while enforcing portfolio constraints.

Portfolio state and mandate constraints affect implementation. Individual financial goals, retirement targets, preferred investment philosophies, and behavioral profiles do not affect candidate ranking, specialist analysis, CIO judgment, or portfolio optimization.

## Daily Capital Intelligence

The default user experience is one concise CIO briefing, not a news feed and not a committee dashboard. It surfaces only material developments and explains:

- what changed;
- why it matters;
- which opportunities or risks changed;
- which active theses strengthened or weakened;
- whether the portfolio should change;
- the recommended action or disciplined no-action result;
- confidence; and
- what evidence would change the conclusion.

The Capital Intelligence Score may remain a supporting environment or evidence indicator. It is not the product’s governing identity, an expected-return estimate, or a trading signal.

## Evaluation and controlled learning

The platform evaluates compounded return, CAGR, benchmark and cash-relative return, drawdown, hit rate, capture, costs, slippage, opportunity cost, thesis failures, attribution, and confidence calibration.

Poor outcomes must be attributed to analysis, sizing, execution, timing, or unavoidable uncertainty. Model changes require point-in-time historical testing, out-of-sample validation, paper trading, comparison with prior versions, governance approval, versioning, and rollback. The system may not autonomously rewrite its process from short-term results.

## Feature test

A core feature belongs only when it improves the platform’s ability to compound capital over the long term while preserving evidence integrity, reproducibility, no-action outcomes, and user clarity.

Features centered on individual financial-goal optimization, retirement planning, behavioral coaching, personalized philosophies, social investing, news feeds, high-frequency trading, unvalidated alternative signals, premature asset expansion, or autonomous process rewriting are out of scope for Version 1.