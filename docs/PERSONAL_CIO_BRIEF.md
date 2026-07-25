# Investor Objectives and Personal CIO Brief

## North Star

Capital Intelligence is the personal Chief Investment Officer for everyday
investors—continuously analyzing the world's financial system, separating signal
from noise, and transforming institutional-quality investment intelligence into
clear, trustworthy guidance that helps people make better long-term portfolio
decisions.

## Purpose

The market-intelligence system and the investor-policy system answer different
questions:

- **Capital Intelligence Score:** how strong and decision-useful is today's
  governed market intelligence?
- **Conviction Trend:** is the underlying investment view strengthening or
  weakening?
- **Portfolio Alignment:** how consistent is the authorized portfolio with the
  investor's recorded objectives and constraints?

Portfolio Alignment is not a probability of achieving a goal. The platform must
not present a funding probability until a separately validated forecasting model
supports that claim.

## Investor policy

`InvestmentPolicyProfile` records the purpose and operating assumptions for the
capital. It keeps financial risk capacity separate from emotional risk
preference and includes:

- primary objective;
- time horizon;
- required return, when explicitly supplied;
- maximum tolerable drawdown;
- minimum liquidity reserve;
- income requirement;
- tax sensitivity; and
- rebalancing tolerance.

`InvestorGoal` records one versioned goal with its priority, target date, target
amount, funded amount, liquidity requirement, and the authorized portfolios that
fund it.

Every update appends a new immutable version. Historical versions are not
rewritten, and Investor Memory cannot silently alter policy.

## Four-question response contract

Every `PersonalCIOBrief` answers:

1. **What changed?** Only the governed change or explicit no-material-change
   result.
2. **Why does it matter?** A plain-language explanation grounded in the same
   evidence.
3. **How does it affect my portfolio?** The authorized holdings, mandate posture,
   liquidity needs, objectives, and conflicts.
4. **Should I do anything?** One formal outcome:
   `no_action`, `monitor`, `review`, `consider_change`, or `urgent_review`.

`no_action` is a successful decision. Every outcome includes review conditions
and evidence lineage.

## Missing context

The platform never invents an objective, target date, risk capacity, or risk
preference. When policy is missing, Portfolio Alignment is `incomplete` and the
brief recommends recording objectives before relying on personalized guidance.

## API

Authenticated, investor-scoped routes:

```text
GET  /v1/investment-policy/{investor_identifier}
POST /v1/investment-policy/{investor_identifier}
GET  /v1/investment-policy/{investor_identifier}/history
GET  /v1/goals/{investor_identifier}
POST /v1/goals/{investor_identifier}
GET  /v1/personal-cio/{investor_identifier}/latest
```

Unauthorized investor identifiers return `404` to avoid disclosing another
investor's existence or policy state.

## Product experience

The authenticated Today screen leads with Portfolio Alignment and the four
questions. Objective editing remains in the sidebar so it does not create a
fifth primary screen. Evidence, committee detail, score history, and review
conditions remain available as progressive detail.

## Operational treatment

The objective database is included in encrypted backups and readiness reporting.
It is stored beside Investor Memory as `database/investment_policy.db` by default.
