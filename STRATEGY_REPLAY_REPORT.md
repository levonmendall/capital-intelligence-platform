# Strategy Replay Report

## Scope and authority

This report completes the point-in-time replay portion of Push 2 using the latest certified Canonical CIO historical artifact available when the evaluation was performed.

- Source certification: GitHub issue `#208`
- Source commit: `6872811a5b20d24a68df4ebe84f42e6d42984519`
- Workflow run: `30666665252`
- Artifact: `8807536231`
- Artifact digest: `sha256:2be00f4d7064a80b621a951ef68d9ec5bfa2d3bf3d28d826a341dcaa82bc3ffc`
- Replay period: 2016-07-31 through 2026-07-31
- Cadence: monthly
- Research only: true
- Execution, real-money, policy-promotion, and performance-claim authority: false

No canonical strategy, threshold, CIO authority, construction rule, portfolio state, or execution behavior was changed.

## Certified replay result

| Measure | Result |
|---|---:|
| Decision cutoffs | 121 |
| Canonical cycle invocations | 118 |
| Blocked cutoffs | 3 |
| Historical observations | 296 |
| Canonical CIO decision observations | 0 |
| Starting portfolio | $250,000 |
| Ending portfolio | $250,000 |
| Ending cash | 100% |

The replay did not produce an investable historical portfolio. Every observation stopped at `pre_cio_qualification`; no candidate reached the six specialists, CIO synthesis, target sizing, construction, or implementation.

## Primary bottleneck

All 296 observations shared the same blocking reason:

> Instrument is intelligence-only because its market or economic exposure lacks a configured capability authority.

The replay therefore demonstrates a **capability and replay-scope bottleneck before the CIO**, not evidence that the CIO independently chose cash 296 times.

## Replay coverage limitation

The replay observations contained only:

| Symbol | Observations |
|---|---:|
| BTC-USD | 118 |
| ETH-USD | 118 |
| SOL-USD | 60 |

All 296 observations were classified as crypto and `intelligence_only`. The current allocatable pilot scope—especially its U.S.-listed cross-asset wrappers—was not represented. This replay cannot establish whether the current 15-instrument pilot strategy is appropriately selective or structurally cash biased.

## Secondary qualification findings

After the universal capability block, the replay recorded:

| Secondary reason | Observations |
|---|---:|
| Expected downside above limit | 67 |
| Worst-case portfolio loss above policy | 42 |
| Probability inconsistent with scenarios | 29 |
| Liquidity below threshold | 14 |
| Evidence-quality dimension below threshold | 6 |

These counts identify research targets, but they do not justify removing a control. Each must be tested on decision-eligible instruments with certified point-in-time evidence.

## Outcome observations

At the governed decision horizon:

- 158 observations were classified as missed opportunities.
- 102 were classified as avoided losses.
- 36 were unresolved.

The underlying returns are crypto-only and contain extreme tails. They are useful for evaluating classification behavior, but they do not authorize a portfolio performance claim or threshold change.

## Conclusion

The historical replay is certified for its stated research boundary, but it is **not sufficient to approve the current strategy, lower thresholds, reset the portfolio, or launch the formal experiment**.

The next valid replay must include the actual decision-eligible pilot instruments, preserve point-in-time evidence across multiple regimes, and produce observations that reach specialist analysis and CIO judgment.
