# Personal CIO Intelligence

PR22 adds three complementary capabilities around the existing Capital
Intelligence Score. The score remains the single daily product identity; these
features explain its direction, remember the investor's own process, and make
capital allocation comparative.

## Investor Memory

Investor Memory is an append-only record of facts explicitly supplied by the
investor or a decision reviewer. It can store:

- how a governed recommendation was handled;
- an explicitly declared preferred risk level;
- behavior patterns observed during a decision;
- mistakes the investor chose to record;
- lessons to carry into future decisions.

The platform does not infer personality, risk tolerance, or mistakes from
unrelated activity. A preferred risk level appears only after a preference event
is recorded. A recurring mistake appears only after the same behavior has been
recorded as a mistake at least twice.

The default local store is:

```text
database/investor_memory.db
```

SQLite triggers reject updates and deletes. Re-appending the same identifier and
payload is idempotent; reusing an identifier for different content is rejected.

## Conviction Trend

Conviction is separate from the 0-100 Capital Intelligence Score. It combines:

- evidence confidence: 50%;
- committee support: 30%;
- committee agreement: 20%.

The versioned `conviction-trend.v1` policy classifies the latest move as rising,
steady, or falling. It also reports the recent streak, score change, and the two
largest component drivers when they move materially.

The trend reads the existing append-only daily snapshot payloads. It never
reruns the intelligence engine and never changes the underlying score.

## Opportunity Cost

Every positive portfolio proposal needs a funding explanation. The
`opportunity-cost.v1` assessment:

1. uses cash above the explicit minimum reserve when permitted;
2. uses only position reductions explicitly supplied as funding candidates;
3. identifies overlapping positions as alternatives for review;
4. reports any unfunded allocation gap;
5. explains liquidity, optionality, forgone upside, diversification, and risk
   budget trade-offs.

The assessment is non-executing. It never selects a sale silently and cannot
bypass the portfolio-fit gate.

## Product surfaces

The Streamlit experience adds:

- conviction direction beside the daily Capital Intelligence Score;
- a conviction history comparison;
- an Investor Memory summary and reflection recorder;
- a non-executing opportunity-cost comparison on the Portfolio screen.

The production API adds read-only endpoints:

```http
GET /v1/conviction/latest
GET /v1/investor-memory/{investor_identifier}
GET /v1/investor-memory/{investor_identifier}/events
```

Investor Memory writes remain inside the trusted application boundary until
authentication and investor-level authorization are implemented.
