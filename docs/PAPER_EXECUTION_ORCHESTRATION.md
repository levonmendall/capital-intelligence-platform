# Paper Execution Orchestration

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

The paper execution layer measures whether an approved `PortfolioConstructionResult` can be implemented under realistic market, cash, liquidity, sequencing, and cost conditions. It is a simulator and evidence producer. It has no broker, network, or live-order authority.

```text
CIO decision
    -> portfolio construction
    -> paper execution batch
    -> sell and funding dependencies
    -> deterministic simulated fills
    -> cash/share/NAV reconciliation
    -> canonical paper-fill journal events
    -> implementation attribution
```

## Authority boundary

The layer may:

- convert construction trade weights into virtual orders;
- apply market-session and holiday controls;
- sequence sells before buys;
- hold dependent buys until named funding sales complete;
- simulate partial fills, rejected orders, cancellation, and expiry;
- apply bid/ask spread, commission, liquidity, ownership, and cash constraints;
- update an isolated virtual cash-and-share ledger;
- reconcile the ledger and measure drift from construction targets; and
- append reconciled `paper_trade_fill` records to the canonical CIO journal.

It may not:

- connect to a broker;
- submit, replace, or cancel a live order;
- alter the CIO action;
- change the construction target;
- treat an unreconciled fill as valid evidence; or
- represent simulated activity as real execution.

## Market and quote controls

A batch requires a configured market calendar and a timezone-aware session result.

- `open` — eligible orders may be simulated.
- `closed` — open orders remain held.
- `holiday` — open orders remain held.

Each order also requires a point-in-time quote that:

- matches the requested symbol;
- is not future-known;
- is within the maximum quote-age policy;
- has positive bid, ask, and last prices;
- has a nonnegative liquidity estimate; and
- is not halted.

A stale, missing, mismatched, or halted quote affects only that order. It cannot manufacture a fill.

## Sequencing and funding

Orders are processed deterministically:

1. sells;
2. independent buys; and
3. buys whose named funding sales have completed.

`TradeProposal.funding_for` is the dependency contract. A buy remains held when any sale designated to fund that symbol is incomplete. Partial proceeds do not silently authorize the full dependent purchase.

## Fill simulation

- Sells fill at the bid.
- Buys fill at the ask.
- The construction trade weight defines requested reference notional using beginning NAV.
- Fill quantity is capped by remaining reference notional, participation policy, owned quantity for sells, and available paper cash for buys.
- Partial fills are permitted only when policy allows them.
- Commission and adverse spread are recorded as realized implementation cost.
- Excess realized cost causes rejection rather than a favorable fabricated fill.

A later attempt may resume only from the exact latest virtual portfolio state. Prior fills, rejections, and held states remain immutable.

## Reconciliation

Before publication, the system proves:

```text
ending NAV
= beginning NAV
+ mark change caused by bid/ask execution
- commissions
```

It also records:

- cash change;
- gross buys and sells;
- beginning and ending NAV;
- target-weight drift for every instrument and cash; and
- the reconciliation difference.

An unreconciled batch fails and publishes no canonical paper fills.

## Append-only evidence

`SQLitePaperExecutionStore` records:

- batch start;
- every attempt snapshot;
- every fill;
- cancellations; and
- failures.

Events use canonical JSON and a contiguous SHA-256 chain. Database triggers block updates and deletes. Exact completed replay is idempotent and repairs missing journal publication without creating duplicate fills.

## CLI

```bash
python run_paper_execution.py \
  --construction artifacts/latest_construction.json \
  --portfolio artifacts/current_paper_portfolio.json \
  --decision-identifier decision:example \
  --session-provider production_calendar:create_provider \
  --quote-provider production_paper_quotes:create_provider \
  --as-of 2026-07-27T15:00:00+00:00 \
  --require-complete
```

The provider factories are external boundaries. The repository does not include a broker adapter. `--require-complete` returns a nonzero exit for held, partial, failed, or cancelled batches.

## Remaining empirical boundary

The orchestration substrate can be validated deterministically in software. Credible implementation claims still require extended paper operation with certified point-in-time quotes, observed spreads and liquidity, realistic outages and halts, and subsequent attribution across market regimes.
