# Capital Intelligence Platform Product Vision

## Product thesis

Capital Intelligence Platform is an explainable multi-asset CIO operating
system for investors who need institutional decision discipline without
institutional infrastructure.

It is not primarily a charting terminal, news reader, trading bot, or
generative stock picker. It connects point-in-time evidence to deterministic
assessments, governed committee decisions, mandate-aware portfolio actions,
and later evaluation.

## Target user

The initial user is a serious independent investor, family-office principal,
advisor, or small investment team that:

- allocates across macro regimes and multiple asset classes;
- evaluates individual public companies and crypto instruments;
- needs repeatable reasoning rather than unstructured market commentary;
- cannot justify or does not want a full institutional terminal stack;
- values auditability, risk controls, and decision review.

The first release is optimized for one accountable decision maker. Team
permissions, enterprise operations, and client reporting follow only after the
core decision loop is trustworthy.

## Core promise

For every recommendation, the platform should answer:

1. What did the system know at the decision time?
2. Which deterministic assessments were produced?
3. What evidence supported and contradicted the conclusion?
4. How did committee policy alter or approve it?
5. Which mandate and risk constraints governed portfolio expression?
6. What happened afterward, and was the process sound?

## Canonical workflow

1. Ingest provider-neutral, point-in-time observations.
2. Assess macro regime, liquidity, credit, market structure, company quality,
   valuation, momentum, and risk.
3. Produce typed opportunities, risks, confidence, and data-quality results.
4. Submit assessments to a governed investment committee.
5. Apply mandates, vetoes, concentration limits, and sizing policy.
6. Record the decision, evidence snapshot, versions, and rationale.
7. Monitor outcomes and separate process quality from investment outcome.

## Asset scope

The architecture supports equities, ETFs, fixed income, commodities, FX, and
crypto. Crypto is first-class and includes spot assets, stablecoins, tokens,
futures, and perpetuals across continuously traded venues.

Initial analytical depth will remain deliberately uneven:

- macro and economic regime first;
- public-company filings and fundamentals second;
- daily market and crypto structure third;
- portfolio construction, evaluation, and backtesting after evidence contracts
  are stable.

## Differentiating principles

- **Decision lineage:** evidence, assessments, votes, policy, actions, and
  outcomes remain linked.
- **Point-in-time honesty:** revisions, restatements, release times, venue
  differences, and unavailable history are explicit.
- **Structured disagreement:** committee members expose conflicting evidence;
  confidence is not manufactured by averaging away disagreement.
- **Process attribution:** evaluation distinguishes a good process with a bad
  outcome from a bad process with a lucky outcome.
- **Cross-asset context:** macro regime and liquidity can influence equity and
  crypto assessments without erasing asset-specific risks.
- **Continuous intelligence, selective attention:** analysis can run in the
  background, but the product interrupts the user only when a change is
  material enough to reconsider portfolio risk.
- **AI restraint:** generative AI explains, queries, and summarizes structured
  results but cannot invent observations or bypass policy.

## MVP

The MVP is complete when a user can:

- select a supported equity, ETF, or major crypto instrument;
- inspect timestamped evidence and data quality;
- receive an explainable macro and instrument assessment;
- run the assessment through committee governance;
- see a mandate-aware model allocation or no-action decision;
- save an immutable decision record;
- revisit the decision after a defined horizon.

The MVP is advisory and paper-only. It does not require brokerage execution,
intraday trading, social features, a strategy marketplace, tax accounting,
custody, or an unconstrained conversational trading agent.

## Explicit exclusions

Until the core workflow is validated, the product will not:

- compete on raw data breadth with Bloomberg or FactSet;
- provide high-frequency execution or order-book trading;
- promise autonomous returns;
- hide missing data behind synthetic precision;
- allow an LLM to override portfolio or committee policy;
- add features solely because another terminal has them.

## Product acceptance test

A feature belongs in the product only if it materially improves at least one
of these outcomes:

- evidence quality;
- analytical quality;
- decision governance;
- portfolio risk control;
- learning from prior decisions.

Features that do not strengthen this loop should remain integrations, optional
views, or out of scope.
