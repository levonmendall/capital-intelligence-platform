# Decision Authority Map

| Actor/component | Permitted authority | Explicit prohibition |
|---|---|---|
| Public information collectors | Acquire and preserve evidence | No recommendations, sizing, or execution |
| Event intelligence | Rank relevance, novelty, corroboration, materiality, exposures | No CIO override or trade authorization |
| Eligible-universe screening | Admit/reject candidates under point-in-time gates | No portfolio action |
| Six specialists | Support, oppose, abstain, veto evidence, propose risk ceilings | No final action and no direct execution |
| CIO service/cycle | Sole authority to choose investment action | Cannot bypass readiness, construction, or governance |
| Construction engine | Convert approved actions into feasible portfolio-level sizes | Cannot invent a buy/sell or exceed CIO/constraint ceilings |
| Headless paper executor | Implement the exact approved construction after gates | No decision, strategy, or live-money authority |
| Reconciler/integrity specialist | Block or certify state publication | Cannot create fills or approve a decision |
| Canonical state store | Append reconciled portfolio events | No analytical authority |
| Historical evaluation/learning | Measure outcomes and propose governed review | No automatic threshold/policy promotion |
| Streamlit/API | Read and explain projections; authenticated admin may invoke operational controls | No investment or execution authority |
| Administrator | Identity/operational control, smoke tests, backups, approved paper controls where policy permits | No live-money authority; no bypass of CIO or construction |
| Anonymous viewer | Public read-only projection of approved fields | No alerts mutation, approval, execution, backup, smoke test, identity, admin, or private telemetry |

## Required authorization chain

```text
ready point-in-time data
  AND complete universe
  AND six-specialist packet
  AND CIO action
  AND feasible construction
  AND paper launch/readiness gates
  AND singular headless executor
  AND successful reconciliation
  => canonical paper-state append
```

Absence of any term blocks the append. No downstream component may manufacture a missing upstream authorization.

## Committee and CIO evolution status

The committee and CIO architecture are **not frozen**. Evidence-backed improvements to specialist roles, analytical methods, inputs, reconciliation, CIO reasoning, portfolio context, and decision controls may be proposed, tested, and promoted through normal governed review.

Unfreezing does not itself change authority. The current six-specialist structure remains canonical until a separately justified and validated change is adopted; the CIO remains the sole investment-action authority; construction remains the independent final portfolio-sizing authority; and advisory components such as the Red Team do not acquire a vote, veto, threshold, sizing, or execution power by implication. Changes must preserve point-in-time evidence, explicit accountability, fail-closed readiness, append-only lineage, and paper-only execution boundaries.
