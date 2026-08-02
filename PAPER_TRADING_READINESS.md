# Paper Trading Readiness

## Current boundary

- Portfolio: one `COMPOUNDING` paper portfolio, USD, $250,000 starting capital.
- Canonical implementation: internal simulated fills persisted through governed execution and reconciliation.
- Instrument scope: every classified liquid public-market instrument may be evaluated and may become paper allocatable through the exact certified active-universe capability publication.
- Bootstrap universe: the original 15 U.S.-listed instruments remain available for startup, smoke tests, and regression coverage; they are not an ownership whitelist.
- Live money: prohibited. No component has real-money authority.

## Readiness assessment

| Gate | State | Boundary |
|---|---|---|
| CIO-only action | Implemented | Six specialists remain advisory; only the CIO issues portfolio actions |
| Complete-universe opportunity process | Implemented in architecture | No candidate-count or shortlist ceiling; production providers must prove complete point-in-time coverage |
| Capability-based paper ownership | Implemented in architecture | Exact identity, evidence, execution, custody, settlement, currency, lifecycle, and risk capability must be current |
| Exact execution universe | Implemented | Missing or mismatched active publication fails closed; there is no static execution fallback |
| Portfolio construction after CIO decision | Implemented | Dynamic search remains subject to cash, risk, liquidity, cost, turnover, concentration, and downside controls |
| Reconciliation before canonical state | Implemented foundation | Restart, partial-fill, corruption, and recovery exercises remain operating requirements |
| Provider/data readiness | Fail closed | Each asset remains unavailable until its required licensed point-in-time domains are complete |
| Production composite readiness | Not equivalent to live-money approval | Current operational, deployment, backup, SLO, and incident gates must remain green |
| Out-of-sample validation | In progress | No proven-alpha or performance claim is permitted |

## Formal experiment boundary

The original `config/paper_experiment_protocol.v1.json` froze the earlier 15-instrument pilot. It is preserved as an immutable historical protocol and cannot be used to evaluate the universal active-universe build after this scope change. A new experiment registration must freeze the exact code, provider capabilities, active-universe publication rules, costs, benchmark, schedule, failure policy, and metrics before new results are interpreted.

Any completed paper experiment remains descriptive evidence awaiting human review. It cannot automatically change thresholds, promote policy, support performance claims, authorize live money, or bypass current capability and reconciliation controls.
