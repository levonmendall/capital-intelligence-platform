# Portfolio Valuation & Execution Integrity Specialist

## Position in the organization

The Portfolio Valuation & Execution Integrity Specialist is a non-voting operational control positioned after CIO approval and portfolio construction. It is not a sixth analytical specialist and does not participate in candidate ranking or the Investment Committee vote.

Its mission is to answer one question:

> Was the approved portfolio action—or subsequent valuation—recorded, valued, and reconciled correctly?

## Authority

The specialist may:

- certify publication of a canonical paper-portfolio execution update;
- certify recurring mark-to-market valuation snapshots;
- hold publication when accounting, pricing, or execution evidence is incomplete;
- require integrity review when fills, shares, cash, cost basis, marks, NAV, or implementation history disagree; and
- preserve an append-only certification record for audit and replay.

The specialist cannot:

- recommend an investment;
- change a CIO decision;
- change a target weight or funding source;
- vote in the Investment Committee;
- submit a broker order; or
- authorize real-money activity.

## Execution certification

Before the paper executor can publish a changed canonical portfolio snapshot, the specialist verifies:

1. Portfolio identity, base currency, and starting capital remain unchanged.
2. Execution reconciliation passed within the configured tolerance.
3. Beginning shares plus buys minus sells equal ending shares.
4. Beginning cash plus sell proceeds minus buy costs and commissions equals ending cash.
5. Every paper fill appears in canonical implementation history.
6. Touched positions have finite quantity, average cost, mark, cost basis, market value, and unrealized gain or loss.
7. Portfolio and valuation timestamps are point-in-time valid.
8. A no-fill attempt does not mutate portfolio identity.

## Valuation certification

Before a recurring price refresh can publish a new canonical snapshot, the specialist verifies:

1. Holdings membership, quantities, and preserved acquisition costs are unchanged.
2. Base-currency cash and implementation history are unchanged.
3. Foreign-currency amounts and preserved cost bases are unchanged while current FX marks may update.
4. Every current mark, market value, cost basis, and unrealized gain or loss is finite and point-in-time valid.
5. NAV movement equals the independently calculated mark and FX movement.
6. The accounting residual remains within tolerance.

## Publication boundary

Both the paper executor and mark-to-market service now calculate their proposed ending state against a temporary portfolio store. The real `canonical_portfolio.db` is updated only after the specialist issues a `certified` result.

A `held` result prevents publication and returns the exact accounting or valuation discrepancy to the calling workflow. Certifications are written to the tamper-evident `portfolio_integrity.db` store located beside the canonical portfolio database.

This control remains paper-only and always records:

```text
investment_decision_authorized = false
real_money_authorized = false
```
