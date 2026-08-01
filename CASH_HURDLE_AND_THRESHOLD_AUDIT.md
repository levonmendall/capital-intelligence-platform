# Cash Hurdle and Threshold Audit

## Decision status

No threshold was changed. With zero production cycles available in this checkout, this document inventories the active hurdle stack and identifies what must be measured before any adjustment can be recommended.

## Active hurdle stack

| Layer | Current default or production value | Cash effect |
|---|---:|---|
| Opportunity evidence score | 70% minimum | Hard reject below the aggregate floor |
| Weakest evidence dimension | 50% minimum | Hard reject when any evidence dimension is below the floor |
| Candidate liquidity | 70% minimum | Hard reject below the liquidity floor |
| Qualification implementation cost | 2% maximum return drag | Hard reject above the cap |
| Asset/horizon expected return | Policy-matrix value; typically 2% diversified liquid, 3% standard, 6% speculative, 8% nonlinear derivative | Applied to horizon-normalized evidence-adjusted return |
| Asset/horizon opportunity edge | Typically 0.3%, 0.5%, 1.5%, or 2% | Compared with the best cost- and reliability-adjusted capital alternative |
| Success probability | Typically 51%, 52%, 56%, or 58% | Based on scenario probability of beating the alternative |
| CIO base defaults | 5% expected return, 1% opportunity edge, 55% success probability | Matrix profiles govern normal candidates; explicit stricter overrides remain possible |
| Robustness | Positive robust/stressed edge, probability-loss and worst-case portfolio limits | Can reject or size down after evidence shrinkage and uncertainty penalties |
| Construction cash edge | 1% minimum over cash after acquisition costs | Removes a CIO-approved positive allocation that does not clear cash after costs |
| Production minimum cash | 5% | Preserves liquidity; does not explain a 100% cash target by itself |
| Production maximum position | 10% | Caps size but does not force zero unless another constraint binds |
| Production maximum batch turnover | 20% | Can reduce or defer an otherwise approved target |
| Portfolio expected-return improvement | 0.01% minimum after costs | Removes all positive allocations when the complete portfolio does not improve enough |
| Portfolio scenario controls | Probability outperforming at least 50%; expected shortfall at least -12%; stressed drawdown at least -20%; liquidity-adjusted loss at least -22% | Can remove every positive allocation |

## Important observations requiring measurement

1. Cash is adjusted for alternative evidence quality and liquidity before candidate comparison. The diagnostic records the resulting structured qualification reason, not just the raw candidate-minus-cash arithmetic.
2. A candidate can pass a participation or exploration lane despite soft full-conviction failures, but the CIO and construction still apply their own return, probability, robustness, funding, and portfolio checks.
3. Similar uncertainty may affect candidate evidence, robustness shrinkage, specialist confidence, reconciliation, CIO target sizing, and construction scenarios. This is a potential repeated-haircut path, not yet a proven defect; Phase 2 must trace the exact evidence origins and applied adjustments.
4. Construction applies a separate 1% cash-replacement edge after the CIO target. A positive CIO decision may therefore become a zero final target. Phase 1 now classifies that transition explicitly.
5. Thresholds vary by economic exposure and horizon. Aggregating all candidates under one headline hurdle would be misleading; reports must group by resolved policy profile.

## Required evidence before changing a threshold

- Conversion and primary reason counts for every production cycle.
- Distribution of raw, evidence-adjusted, reconciled, robust, and stressed returns versus cash.
- Count and weight of candidates within 10, 25, and 50 basis points of each binding hurdle.
- Frequency with which one candidate is rejected at multiple successive layers for the same underlying risk.
- Point-in-time replay showing return, drawdown, avoided loss, and missed opportunity effects.
- Shadow-only comparison using identical inputs; no threshold change receives construction or execution authority.

## Go/no-go for threshold changes

Current decision: **NO-GO**. There is no production-cycle denominator and Phase 2/3 evidence is incomplete. The strategy remains canonical as written.

## Rollback and authority

No configuration, policy version, or threshold was edited. CIO, construction, governance, execution, and real-money authority changed: **no**.

