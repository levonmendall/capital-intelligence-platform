# Paper Trading Readiness

## Current boundary

- Portfolio: one `COMPOUNDING` paper portfolio, USD, $250,000 starting capital.
- Canonical implementation: internal simulated fills persisted through governed execution and reconciliation.
- Alpaca: separate paper-account transport and round-trip validation; not the canonical portfolio ledger.
- Live money: prohibited. No component has real-money authority.
- Pilot universe: 15 bounded U.S.-listed instruments (`VTI`, `VXUS`, `GOVT`, `LQD`, `HYG`, `SGOV`, `DBC`, `GLD`, `UUP`, `IBIT`, `VNQ`, `DBMF`, `WTPI`, `VIXY`, `BTAL`) with explicit caps and IEX limitations.

## Readiness assessment

| Gate | State | Reason |
|---|---|---|
| CIO-only action | Implemented in domain contracts | Must be protected by golden tests |
| Portfolio construction after decision | Implemented | Requires full-path certification |
| Paper-only transport | Implemented by policy/config | Needs endpoint/account prohibition chaos tests |
| Singular execution authority | **Not ready** | Headless operator and Streamlit worker coexist |
| Reconciliation before canonical state | Implemented foundation | Restart/partial-fill chaos coverage incomplete |
| Data readiness | Fail-closed foundation | Broad all-market providers remain blocked; pilot must be labeled bounded |
| Production composite readiness | **Not ready** | Render checks Streamlit only |
| Deterministic archives | **Not ready** | `st_mtime` ordering remains |
| PIT historical certification | **Not ready** | Material domains incomplete |
| Formal experiment | **Not ready** | Launch policy is not a frozen experimental protocol |
| Multi-week soak | Not launched under versioned protocol | PR12 |

## Formal experiment requirements

PR12 must freeze a versioned protocol before results are interpreted: hypothesis, start/end criteria, universe, providers, decision schedule, thresholds, costs, capital/cash rules, failure handling, metrics, benchmark, attribution, missing-data policy, change-control, minimum weeks/cycles, and a rule that results can only generate a reviewed proposal—not directly change thresholds or claim performance.

## Launch decision

Continue engineering and deterministic paper rehearsals. Do not call the platform production paper-trading ready and do not begin performance claims until PR1-PR11 gates pass and PR12 records an approved experiment version.
