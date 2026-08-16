# Runtime Influence Registry

## Purpose

Capital Intelligence must distinguish **implemented**, **reachable**, and **decision-influential** capabilities. A feature is not considered connected merely because code exists, a class can be instantiated, or an output is persisted.

The canonical audit is implemented in `governance/runtime_influence_registry.py` and executed by `scripts/audit_runtime_connectivity.py`. Release validation runs the audit with `--require-valid` and publishes `reports/runtime-connectivity-audit.json`.

## Lifecycle classes

Every production Python module receives one lifecycle classification in the generated audit:

- **AUTHORITATIVE** — owns a governed live production boundary.
- **DECISION_INPUT** — may influence a governed CIO input but cannot independently authorize capital.
- **GOVERNED_ADVISORY** — produces advice or monitoring contracts available to the governed process.
- **LEARNING_CALIBRATION** — evaluates outcomes and may alter reliability/confidence only through an explicit governed feedback path.
- **SHADOW** — may run and be evaluated but cannot influence a production decision.
- **PRESENTATION_ONLY** — explains authoritative state and cannot authorize or alter it.
- **OPERATIONAL** — runs or supports production without investment authority.
- **EXPERIMENTAL** — development/rehearsal capability outside production authority.
- **SUPERSEDED** — retained only while an older generation is being retired.
- **ORPHANED** — production-like code with no static reachability from a recognized runtime entrypoint.

`ORPHANED` is an audit finding, not an authority grant.

## Influence contracts

High-meaning capabilities are explicitly declared as `CapabilityContract` records. A governed production capability must identify:

1. producer module(s),
2. consumer module(s),
3. runtime entrypoint(s),
4. the downstream state it is allowed to influence,
5. a feedback path when the capability learns/calibrates future decisions,
6. counterfactual tests when appropriate.

The audit fails release validation if an authoritative, decision-input, advisory, or learning capability loses its declared producer/consumer/runtime connection or required influence contract.

## Current explicit status

The registry deliberately makes architectural boundaries visible rather than optimistic:

- The canonical CIO decision chain is **AUTHORITATIVE**.
- Forward intelligence is a **DECISION_INPUT** through the existing specialists.
- Active-investor expression/lifecycle output is **GOVERNED_ADVISORY**.
- The reactive monitoring plan is **GOVERNED_ADVISORY**: the live reassessment runtime reads the latest hash-chain-verified plan, evaluates only qualified point-in-time evidence against declared dependencies, and may request a canonical CIO reassessment. It has no portfolio, construction, execution, policy-change, or real-money authority.
- Investor-material reassessment is **OPERATIONAL** and may request CIO reassessment only.
- Causal-intelligence sidecar output is **SHADOW**.
- Forecast calibration is **SHADOW** until a governed feedback consumer changes future confidence/reliability.
- Decision Intelligence v3 is **PRESENTATION_ONLY** / downstream measurement.
- Universal Capability Graph, automatic eligibility factory, and universal paper contract remain **SHADOW** until a production evidence owner can supply complete per-instrument point-in-time capability proofs. Provider visibility or configuration defaults are not certification evidence.
- Canonical paper execution remains **AUTHORITATIVE** and paper-only. Provider readiness is evaluated against the exact construction: Alpaca credentials are mandatory when an Alpaca-backed instrument is present, while direct-only constructions proceed to their own provider/session/quote/liquidity controls without a false global Alpaca dependency.

These statuses are expected to change only through reviewed code that also updates the contract and tests.

## Counterfactual standard

For a capability declared as a production decision input or governed advisory input, validation should be able to change that input while holding the rest of the decision context constant and observe the declared downstream consequence. Examples:

- a materially worse forecast calibration lowers future confidence,
- a capital-flow reversal alters the relevant expression or requests reassessment,
- a regime-transition probability change alters the appropriate risk/posture input,
- a thesis invalidation requests prompt CIO review,
- a superior replacement changes opportunity-cost/ranking evaluation.

The reactive-monitoring contract now includes this proof: changing a declared thesis-specific evidence dependency changes whether the same qualified public evidence produces a reassessment match.

If a declared decision or advisory input can change materially without changing any permitted downstream target, the feature is functionally disconnected and should fail its counterfactual test or be reclassified as shadow.

## Governance invariants

The registry itself has no investment authority. It must not:

- lower investment thresholds to create trades,
- authorize live money,
- allow presentation or learning systems to independently change the portfolio,
- convert a shadow model into a decision input without explicit review,
- repair upstream evidence synchronously from a downstream decision or execution boundary.

The portfolio remains paper-only and CIO authority remains the sole authorization path for investment action.
