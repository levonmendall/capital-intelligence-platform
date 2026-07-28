# Performance-accounting validation contract

The portfolio performance ledger is release-ready only when deterministic tests prove all of the following:

- buys include transaction costs in average cost;
- partial and complete sells relieve the proportional average-cost basis and record net realized P&L;
- open positions reconcile current market value, preserved basis, unrealized P&L, and unrealized return;
- non-base positions preserve acquisition FX basis while current marks use point-in-time FX;
- non-base cash reports FX gain or loss independently from position P&L;
- dividends, interest, coupons, fees, taxes, corporate-action cash, and variation margin affect investment P&L exactly once;
- contributions and withdrawals affect NAV but not investment P&L;
- share splits preserve total cost basis, market value, and P&L;
- mark-to-market publication rejects missing, extra, stale, future-known, halted, or identity-inconsistent evidence;
- every execution reconciles NAV and the accounting residual before a canonical snapshot is appended;
- legacy migration reproduces ending quantities and cost basis without inventing a balancing gain or loss; and
- append-only portfolio and execution hash chains remain valid.

The deterministic release suite and security review remain mandatory in addition to these focused accounting tests.
