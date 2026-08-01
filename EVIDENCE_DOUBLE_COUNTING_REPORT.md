# Evidence Double-Counting Report

## Conclusion

The system has an explicit dependency-aware discount in specialist return reconciliation, but it does not apply that same dependency adjustment to every downstream use of specialist support and confidence. It also subjects the same broad uncertainty, downside, and cost concepts to several sequential controls. Some repetition is intentional defense in depth; the current evidence cannot prove which layers are redundant or harmful without point-in-time ablation.

No penalty or threshold was removed in this phase.

## Repeated-haircut map

| Underlying information | Successive uses | Current assessment |
|---|---|---|
| Evidence quality | Opportunity hard floor → robustness shrinkage → evidence specialist confidence/veto → CIO evidence-deficiency gate → CIO final confidence → confidence-aware target | Same six dimensions affect eligibility, return, confidence, and size. Potentially justified, but economically cumulative. |
| Forecast uncertainty | Forecast-quality minimum and abstention → reconciliation confidence scaling → scenario probability/return adjustment → post-reconciliation robustness → ensemble dispersion/confidence → target scaling → construction scenarios | Strong repeated path; must be ablated as one information category. |
| Shared specialist origins | Reconciliation overlap discount → unadjusted ensemble engine count/support/alignment → unadjusted median confidence and support ratio in CIO confidence | Confirmed partial double counting of correlated confirmation outside return reconciliation. |
| Downside/tail risk | Candidate qualification limit → robust/stressed edge and worst-case checks → forecast path drawdown → CIO downside gate → robust maximum supported weight → construction expected shortfall/stressed drawdown/liquidity-adjusted loss | Several controls operate at candidate, slice, and portfolio levels. Distinct scopes exist, but duplicate economic penalty is plausible. |
| Liquidity and costs | Screening liquidity/cost gates → alternative reliability/liquidity penalties → portfolio preview → construction 1% cash edge after acquisition costs → turnover/cost/ADTV constraints → execution quote/slippage controls | Controls span forecast, construction, and actual implementation. Measurement must separate legitimate stage-specific costs from repeated forecast haircuts. |
| Historical reliability | Every specialist confidence ceiling → historical position multiplier → CIO final confidence ceiling | The code comments say the position multiplier is applied once, but confidence is capped at each specialist and again at CIO aggregation. |
| Opportunity/cash hurdle | Screening best-alternative edge → CIO reconciled/robust edge → confidence-aware target edge scale → construction cash edge and portfolio-improvement floor | A positive opportunity can clear one layer and be removed later by another differently defined cash hurdle. |
| Agreement | Reconciliation role adjustments → ensemble supportive ratio/alignment/confidence → CIO directional support/median confidence/coverage | Correlated roles may contribute multiple times to stage, confidence, and size. |

## What is not double counting by definition

- A candidate-level downside test and a portfolio-level drawdown test are not automatically duplicates; one evaluates the asset distribution and the other the complete portfolio.
- Forecast implementation cost and realized paper slippage are different quantities if the forecast is charged once and the later value measures execution error.
- Evidence eligibility, decision confidence, and target size may legitimately use the same evidence if each function is calibrated jointly rather than treated as independent confirmation.
- A fail-closed integrity veto is a governance boundary, not an expected-return haircut.

## Confirmed versus unresolved findings

### Confirmed

1. Return reconciliation discounts shared evidence origins.
2. Growth-ensemble coverage, support, alignment, and confidence do not use those origin discounts.
3. CIO final confidence combines candidate evidence score, evidence-officer confidence, median confidence, directional support, coverage, origin count, and coverage again in a multiplicative term.
4. Evidence and uncertainty feed both eligibility and target sizing.
5. Construction can remove a positive CIO target through a new cash-edge or portfolio-scenario test.

### Unresolved until replay

- Whether the repeated controls materially increase time in cash.
- Whether removing one layer increases drawdown more than return.
- Whether evidence-quality penalties are calibrated jointly or independently.
- Whether correlated positive opinions or correlated negative opinions dominate current decisions.
- Whether avoided losses compensate for missed opportunities.

## Required Phase 3 ablations

- Remove one specialist at a time while preserving identical point-in-time inputs.
- Remove each information category—evidence quality, forecast uncertainty, downside/tail, costs/liquidity, and historical reliability—one at a time.
- Compare dependency-weighted versus simple specialist support in shadow only.
- Compare current repeated haircuts with a shadow calculation that charges each declared risk category once while retaining fail-closed integrity vetoes.
- Attribute changes at screening, CIO approval, initial target, construction target, return, drawdown, turnover, avoided losses, and missed opportunities.

All alternatives remain append-only and have no construction or execution authority.

## Rollback and authority

This report changes no formula. The trace can be rolled back by redeploying prior code; existing events remain immutable. CIO, construction, governance, execution, and real-money authority changed: **no**.

