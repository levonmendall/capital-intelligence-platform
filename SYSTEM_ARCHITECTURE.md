# System Architecture

## Governing architecture

```text
Information and point-in-time provider evidence
  -> educational event interpretation (non-authorizing)
  -> complete eligible-universe publication
  -> exactly six independent specialist analyses
  -> CIO decision (sole investment-action authority)
  -> portfolio construction and sizing (implements, cannot originate action)
  -> paper execution authority (implements approved construction only)
  -> reconciliation and integrity certification
  -> canonical append-only portfolio state
  -> outcome evaluation and governed learning (non-authorizing)
  -> read-only API and four-screen presentation
```

## Required layer contracts

| Layer | Input | Output | May authorize portfolio change? |
|---|---|---|---|
| Information | Raw public/provider records with provenance | Immutable observations/events | No |
| Interpretation | Events plus exposure context | Educational relevance/materiality | No |
| Screening | Point-in-time security master and coverage | Complete eligible universe | No |
| Specialists | Candidate evidence packets | Six independent analyses | No |
| CIO | Candidate + six analyses + portfolio context | Buy/increase/hold/reduce/exit/no-change | **Yes, investment action only** |
| Construction | CIO actions + current canonical state + costs/constraints | Sized feasible construction | Cannot originate action |
| Paper execution | Approved construction + readiness | Simulated fills | Cannot alter decision or size |
| Reconciliation | Expected construction + fills + state | Certified/blocked publication | No |
| Canonical state | Reconciled event | New append-only state | Records only |
| Learning | Historical point-in-time evidence/outcomes | Evaluation and proposed review | No automatic policy promotion |
| Presentation | Read models | Streamlit/API views | No |

## Non-negotiable invariants

- Exactly one portfolio: `COMPOUNDING`, USD, $250,000 initial capital.
- Objective: maximize long-term compounded portfolio returns after costs.
- Data readiness fails closed; unavailable or stale required evidence blocks advancement.
- Sizing is portfolio-level and follows CIO decisions.
- Decisions, constructions, fills, reconciliations, states, and evaluations retain append-only lineage.
- Historical evaluation respects what was available at each cutoff.
- Execution is paper-only; live-money authority is absent and prohibited.
- Information, forecasts, UI, execution, and learning cannot independently authorize a change.
