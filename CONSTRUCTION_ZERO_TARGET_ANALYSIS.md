# Construction Zero-Target Analysis

## Decision status

No construction rule was changed. The current checkout has no production construction journal, so no observed zero-target frequency can be claimed. This audit identifies every active path that can convert a positive CIO target into no new exposure and adds explicit measurement for that transition.

## Active zero-target paths

| Path | Structured evidence | Diagnostic classification |
|---|---|---|
| Candidate fails the 1% cash edge after acquisition costs | Construction block names the symbol and cash alternative | Failure to exceed cash hurdle; liquidity/cost may contribute |
| Requested target is not above the current position after caps | “no positive allocation within its position limit” | Construction constraint |
| Cash, concentration, factor, correlation, turnover, cost, liquidity, or funding constraints allow no increase | Construction block and constraint checks | Construction constraint, with liquidity/cost when explicit |
| Complete-portfolio optimizer omits an approved intent | Optimizer omission block | Approved target reduced to zero |
| Expected return after costs fails the 0.01% portfolio improvement floor | Portfolio-level block | Approved target reduced to zero and insufficient return |
| Scenario portfolio fails probability, shortfall, stressed drawdown, or liquidity-adjusted loss controls | Portfolio-level scenario block | Approved target reduced to zero plus downside/tail risk |
| Any final constraint remains unsatisfied | Engine falls back to the current portfolio and emits no trades | Construction constraint; approved target reduced to zero for a new candidate |
| Emergency de-risking has incomplete reductions | Positive allocations prohibited | Construction constraint |
| Derivative lifecycle is not authorized | Analysis-only block | Construction constraint; no live-money authority |

## Minimum-position finding

The active engine preserves `minimum_weight` for existing holdings when considering funding reductions. It does **not** define a general minimum new-position rule that independently eliminates small new allocations. The diagnostic retains `minimum_position_rule` as a closed category so any provider- or execution-specific minimum can be measured if it appears, but current source inspection does not support blaming a general minimum-position gate for persistent cash.

## Target reconciliation

For every decision candidate, Phase 1 records:

- CIO action and decision identifier;
- risk-adjusted initial target;
- construction request identifier and status;
- final symbol target;
- construction blocks and constraint evidence; and
- later canonical simulated-fill presence.

A positive initial target with no positive final target is always labeled `approved_target_reduced_to_zero`. The original block remains a contributing reason, so the report can distinguish optimizer omission, cash edge, portfolio-return, tail-risk, turnover, concentration, and liquidity causes.

## Required production measurements

- Number and percentage of positive CIO targets reduced to zero.
- Requested versus final target-weight distribution.
- Binding block/constraint frequency and co-occurrence.
- Expected-return improvement immediately before removal.
- Scenario metric distance from each limit.
- Turnover, cost, cash, concentration, liquidity, and funding headroom.
- Paper execution failure rate only after a nonzero construction exists and the execution observation window has closed.

## Acceptance criteria

- A nonzero CIO target cannot disappear without a candidate-level zero-target classification.
- Construction blocks remain verbatim in append-only diagnostic evidence.
- Existing holdings and new candidates are not conflated.
- Absence of construction after a CIO abstention is not mislabeled a construction failure.
- Absence of an immediate fill is not mislabeled an execution failure.

## Rollback and authority

No construction logic or threshold changed. Rollback removes only the recorder call; existing diagnostic events stay append-only. CIO, construction, governance, execution, and real-money authority changed: **no**.

