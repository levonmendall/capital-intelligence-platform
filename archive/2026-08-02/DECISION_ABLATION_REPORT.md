# Decision Ablation Report

## Purpose

This report asks which observed blocking reasons can be isolated using the certified replay evidence. It does not remove a production rule. Ablations are research-only counterfactuals over immutable replay records.

## One-reason-at-a-time result

| Removed reason category | Observations with no remaining recorded blocker |
|---|---:|
| Capability authority | 191 |
| Downside | 0 |
| Evidence quality | 0 |
| Liquidity | 0 |
| Success probability | 0 |
| Worst-case portfolio loss | 0 |

Removing the capability-authority block alone would leave 191 of 296 observations without another recorded qualification reason. This is a diagnostic result, not an approval to make crypto allocatable.

## Conditional secondary blockers

After treating capability certification as a hypothetical prerequisite:

| Secondary category | Recorded occurrences |
|---|---:|
| Downside | 67 |
| Worst-case portfolio loss | 42 |
| Success probability | 29 |
| Liquidity | 14 |
| Evidence quality | 6 |

The repeated downside and worst-case controls are plausible stacked-conservatism candidates. The current artifact cannot determine whether they are duplicate penalties or distinct protections because the observations never reached specialist reconciliation, CIO robustness, target sizing, or construction.

## Committee and CIO ablation status

Committee, specialist, CIO, sizing, and construction ablations are **not evaluable** from this artifact:

- Canonical CIO decision observations: 0
- Six-specialist observations: 0
- Initial target observations: 0
- Construction observations: 0
- Implementation observations: 0

Removing or reweighting a specialist based on these records would manufacture evidence that does not exist.

## Required evidence

A valid next-stage ablation must compare identical point-in-time candidates while removing one information category or specialist at a time and must measure:

- funnel progression;
- CIO action and confidence;
- initial and final target;
- return versus cash and benchmark;
- downside and drawdown;
- avoided losses and missed opportunities;
- turnover and cost.

## Conclusion

The only strongly identified bottleneck is the pre-CIO capability-authority gate and the mismatch between historical replay scope and the allocatable pilot. No production threshold or committee rule should be changed from this ablation alone.
