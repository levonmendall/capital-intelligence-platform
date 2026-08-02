# Committee and CIO Decision-System V2

## Objective

Strengthen the existing governed investment process without changing the canonical portfolio objective, CIO-only authority, six-specialist structure, paper-only boundary, or fail-closed evidence and implementation controls.

This work is tracked in issue #347 and must be delivered as ordered, independently reviewable pull requests.

## Protected invariants

- One governed $250,000 USD `COMPOUNDING` paper portfolio.
- Exactly six advisory specialists.
- CIO-only authority to approve portfolio changes.
- Complete point-in-time evidence and append-only lineage.
- No threshold reductions merely to produce trades.
- No live-money authority.
- Risk-adjusted CIO initial target followed by independent construction.
- Historical learning cannot automatically create trades or promote policy.

## Delivery sequence

### PR 1 — Economic qualification consistency

- Require positive robust edge over the governing alternative for every positive allocation, including exploration and participation.
- Preserve research-only `WATCH`/`RESEARCH` outcomes for candidates that remain analytically interesting but do not clear the economic hurdle.
- Preserve existing return, risk, liquidity, cost and portfolio-survival thresholds.

### PR 2 — Applicable evidence and valuation completeness

- Introduce one versioned asset-class applicability matrix.
- Require the appropriate business, valuation or return-driver packet before a new or increased exposure can proceed.
- Treat missing applicable analysis as incomplete evidence rather than an ordinary specialist abstention.

### PR 3 — Uncertainty attribution and independent consensus

- Separate hard integrity failures from ordinary investment uncertainty.
- Record uncertainty lineage and prevent repeated charging without explicit attribution.
- Replace raw specialist agreement with evidence-origin-adjusted effective independent agreement for confidence, opposition, persistence, stage and sizing.

### PR 4 — Canonical policy authority

- Consolidate acquisition, downside, probability, edge, cap and persistence thresholds under one versioned authority.
- Remove or de-authorize overlapping threshold copies.

### PR 5 — Construction reconciliation

- Return construction results to the CIO record.
- Persist initial target, adjusted target, final target, displacement, funding conflict, minimum-position elimination and exact binding constraints.

### PR 6 — Strategic business analysis

- Add structured product, segment, geography, customer, supplier, backlog, pricing, capacity, inventory, incremental-margin, capital-intensity, management-allocation, dilution and theme-exposure evidence.

### PR 7 — Trend, crowding and market-cycle analysis

- Add absolute and relative trend, breadth, revision breadth, volume confirmation, concentration, crowding, acceleration, cross-market confirmation and valuation-versus-earnings attribution.

### PR 8 — Candidate and marginal portfolio risk

- Add conditional loss, candidate expected shortfall, drawdown duration, recovery time, stress liquidity, days to exit, tail dependence and marginal portfolio expected-shortfall contribution.

### PR 9 — Structural theme and demand transmission

- Add a non-authoritative value-chain graph, theme-stage classifier, bottleneck detector, measurable transmission evidence, investable exposure mapping and competing causal paths.
- The engine may nominate and enrich candidates but cannot decide, size, construct, authorize or execute.

### PR 10 — Monetary policy and cross-asset transmission

- Add policy-regime classification, central-bank reaction-function evidence, policy motive, transmission channels, cross-market confirmation and market-implied-expectation comparison.
- Preserve probabilistic, conditional reasoning; never hard-code `QE = risk-on`, `inflation = risk-off`, or `peak rates = buy duration`.

### PR 11 — Joint-candidate portfolio analysis

- Add bounded complementary, mutually exclusive, dominated and basket-only candidate evaluation before final CIO targets.

### PR 12 — Evidence-outage handling

- Add age-of-last-validation, confidence decay, substitute-evidence rules and escalation from hold to reduction where continued observation becomes inadequate.

### PR 13 — Calibration and decision-value evaluation

- Add Brier score, calibration curves, return/downside error, interval coverage, regime/asset/specialist calibration, missed opportunities, false positives and gate contribution analysis.
- Results remain research-only and cannot automatically lower thresholds.

## Validation required for every PR

- Focused deterministic tests for the new behavior.
- Existing committee, CIO, construction, execution and reconciliation regressions.
- Full repository validation.
- Desktop and iPhone browser gates where presentation is affected.
- Provider and point-in-time validation where data paths are affected.
- Historical replay compatibility.
- Security review and paper-only enforcement.

## Completion standard

The program is complete only when every positive allocation has complete applicable evidence and a positive robust economic advantage over its governing alternative, correlated evidence cannot create false consensus, uncertainty is not double-counted, causal macro and thematic evidence is available to the existing specialists, construction results are fully reconciled, and calibration can distinguish useful controls from duplicated conservatism.