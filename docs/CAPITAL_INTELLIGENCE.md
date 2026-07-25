# Capital Intelligence Score and Decision Replay

## Daily identity surface

The Capital Intelligence Score is one explainable number from 0 to 100. It is
calculated from point-in-time evidence confidence, data coverage, data quality,
committee support, committee agreement, and the positive spread between
expected return and expected risk.

The score measures how strong and usable the current intelligence is. It is not
a price target, return forecast, probability of profit, or position size.
Direction remains visible in the environment, risk, committee, and portfolio
impact fields.

The default policy is versioned and intentionally produces the following daily
shape:

```text
Today's Capital Intelligence
82
Environment: Constructive
Risk: Moderate
Committee: 6–0 Favor Risk Assets
Portfolio impact: Consider holding more diversified risk assets.
```

Every component is retained in the API response so a user can drill into the
underlying screens without turning the primary surface into a dashboard.

## Decision Replay

Decision Replay reconstructs a major decision as an ordered chain:

1. the market event and evidence release;
2. the point-in-time environment change;
3. the committee vote and rationale;
4. the portfolio implication or mandate-aware permitted change;
5. the later benchmark-relative outcome; and
6. the recorded lesson.

Original reasoning is never rewritten with later information. Performance and
lessons are explicitly labeled as hindsight, while the original run, decision,
and evidence identifiers remain attached for auditability.
