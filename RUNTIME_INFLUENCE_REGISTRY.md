# Runtime Influence Registry

## Purpose

Capital Intelligence must distinguish **implemented**, **reachable**, **decision-influential**, and **intentionally non-live** capabilities. A feature is not considered connected merely because code exists, a class can be instantiated, or an output is persisted.

The baseline registry is implemented in `governance/runtime_influence_registry.py`. Explicit non-live dispositions live in `governance/runtime_module_dispositions.py`, and high-meaning live convergence contracts live in `governance/runtime_convergence_contracts.py`. `scripts/audit_runtime_connectivity.py` combines those controls. Release validation runs the audit with `--require-valid` and publishes `reports/runtime-connectivity-audit.json`.

## Lifecycle classes

Every production Python module receives one effective lifecycle classification in the generated audit:

- **AUTHORITATIVE** — owns a governed live production boundary.
- **DECISION_INPUT** — may influence a governed CIO input but cannot independently authorize capital.
- **GOVERNED_ADVISORY** — produces advice or monitoring contracts available to the governed process.
- **LEARNING_CALIBRATION** — evaluates outcomes and may alter reliability/confidence only through an explicit governed feedback path.
- **SHADOW** — may run or be evaluated but cannot influence a production decision until separately promoted.
- **PRESENTATION_ONLY** — explains authoritative state and cannot authorize or alter it.
- **OPERATIONAL** — runs or supports production without investment authority.
- **EXPERIMENTAL** — development/rehearsal capability outside production authority.
- **SUPERSEDED** — retained only while an older generation or compatibility surface is being retired.
- **ORPHANED** — inferred production-like code with no static reachability from a recognized runtime entrypoint and no explicit architectural disposition.

The release gate requires **zero ambiguous ORPHANED modules**. An intentionally unreachable module must therefore be explicitly dispositioned with a lifecycle and rationale. A shadow, experimental, or superseded module also fails the gate if it later becomes runtime-reachable without a deliberate promotion change.

## Influence contracts

High-meaning capabilities are explicitly declared as influence contracts. A governed production capability must identify:

1. producer module(s),
2. consumer module(s),
3. runtime entrypoint(s),
4. the downstream state it is allowed to influence,
5. a feedback path when the capability learns/calibrates future decisions,
6. counterfactual tests when appropriate.

The audit fails release validation if an authoritative, decision-input, advisory, or learning capability loses its declared producer/consumer/runtime connection or required influence proof.

Two convergence contracts additionally prove the most consequential connections:

- **Global rotation production cycle — AUTHORITATIVE.** `application.compounding_executor` explicitly selects `GlobalOpportunityRotationCanonicalCIOCycle`; no module-global CIO-cycle monkey-patch is used. The cycle can affect authoritative opportunity rotation, the six-specialist preliminary pass, jointly optimized marginal-capital targets, and ultimately the canonical CIO decision.
- **Governed historical learning feedback — LEARNING_CALIBRATION.** Matured, point-in-time, horizon-aligned outcomes flow through the canonical historical-learning manifest and `HistoricalLearningResolver`, then into `CandidateSpecialistContext` and specialist historical calibration before CIO synthesis. The path may only make confidence/sizing more conservative and cannot promote policy or authorize execution.

## Current explicit status

The registry deliberately makes architectural boundaries visible rather than optimistic:

- The canonical CIO decision chain is **AUTHORITATIVE**.
- Forward intelligence is a **DECISION_INPUT** through the existing six specialists.
- Global opportunity rotation is explicitly bound into the production executor and is **AUTHORITATIVE** inside the existing CIO/construction chain.
- Governed historical learning is **LEARNING_CALIBRATION** and is consumed before CIO synthesis.
- Active-investor expression/lifecycle output is **GOVERNED_ADVISORY**.
- The reactive monitoring plan is **GOVERNED_ADVISORY**: the live reassessment runtime reads the latest hash-chain-verified plan, evaluates only qualified point-in-time evidence against declared dependencies, and may request a canonical CIO reassessment. It has no portfolio, construction, execution, policy-change, or real-money authority.
- Investor-material reassessment is **OPERATIONAL** and may request CIO reassessment only.
- Causal reasoning, claim-level forecast calibration/registry, investment graphs, asset-specific underwriting, global-macro overlays, primary-source comparison, structural-break research, thesis-learning research, and value-of-information research are explicitly **SHADOW** until separately certified and promoted.
- Champion/challenger model experiments and atomic relative-value execution are explicitly **EXPERIMENTAL** rather than hidden production paths.
- Compatibility/older generations such as the standalone mispriced-change cycle, document-change facade, and legacy quote interface are explicitly **SUPERSEDED** or operational compatibility surfaces.
- Decision Intelligence v3 is **PRESENTATION_ONLY** / downstream measurement.
- Universal Capability Graph, automatic eligibility factory, and universal paper contract remain **SHADOW** until a production evidence owner can provide complete, point-in-time per-instrument capability proof. Configuration defaults or provider visibility are not sufficient proof and must not manufacture paper authority.
- Canonical paper execution remains **AUTHORITATIVE** and paper-only.

These statuses may change only through reviewed code that also updates the relevant production consumer, influence contract, counterfactual tests, and release validation.

## Counterfactual standard

For a capability declared as a production decision input or governed advisory input, validation should be able to change that input while holding the rest of the decision context constant and observe the declared downstream consequence. Examples:

- a materially worse certified learning history lowers future confidence or sizing,
- a capital-flow reversal alters the relevant expression or requests reassessment,
- a regime-transition probability change alters the appropriate risk/posture input,
- a thesis invalidation requests prompt CIO review,
- a superior replacement changes opportunity-cost/ranking evaluation.

The forward-intelligence, global-rotation, governed historical-learning, and reactive-monitoring contracts all name regression/counterfactual tests that prove their permitted downstream effects.

If a declared decision or advisory input can change materially without changing any permitted downstream target, the feature is functionally disconnected and should fail its counterfactual test or be reclassified as shadow.

## Governance invariants

The registry and convergence controls have no investment authority. They must not:

- lower investment thresholds to create trades,
- authorize live money,
- allow presentation or learning systems to independently change the portfolio,
- convert a shadow model into a decision input without explicit review and proof,
- treat provider visibility or configuration defaults as capability certification,
- repair upstream evidence synchronously from a downstream decision or execution boundary.

The portfolio remains paper-only and CIO authority remains the sole authorization path for investment action.
