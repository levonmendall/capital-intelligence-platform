# Point-in-Time Decision Evaluation

Every recommendation is evaluated as a capital-allocation decision, not as an isolated prediction.

The governing loop is:

1. compare the candidate with cash, current holdings, and every other qualified use of capital;
2. make the CIO decision from evidence available at one decision timestamp;
3. implement the approved expression through portfolio construction;
4. create and continuously monitor an explicit thesis for owned positions; and
5. evaluate the process and realized outcome from the immutable decision snapshot.

## Immutable decision snapshot

`DecisionEvidenceSnapshot` is created for every CIO decision. It records:

- the candidate and CIO decision identifiers;
- the decision timestamp, price, horizon, expected return, downside, probability of success, and confidence;
- the complete original capital-alternative set, including cash and current holdings;
- each alternative's expected return, implementation cost, evidence quality, liquidity, and current weight;
- opportunity rank, effective opportunity cost, and opportunity edge;
- all evidence identifiers with availability timestamps;
- model, policy, and code versions;
- the six specialist roles, vetoes, and implementation blocks;
- recommended and implemented portfolio weights;
- construction status and estimated implementation cost; and
- the explicit thesis, assumptions, invalidation conditions, and monitoring indicators.

The snapshot rejects evidence with an availability timestamp later than the decision. Its canonical JSON fingerprint changes if any original decision input changes.

The snapshot also preserves the baseline alternative, the true best alternative, the resolved asset/horizon policy profile, prior-decision lineage, persistence cycles, hysteresis status, reconciled scenario distribution, and evidence-dependency lineage needed for exact replay.

## Realized outcome join

`RealizedDecisionOutcome` is appended after the evaluation horizon. It does not overwrite the snapshot.

The outcome must provide realized returns for exactly the alternatives that existed in the original capital set. Missing alternatives and newly introduced hindsight alternatives are rejected.

The evaluator also requires:

- decision-to-horizon return;
- implementation-to-horizon return;
- actual implementation cost;
- cash return;
- benchmark return;
- passive-portfolio return; and
- immutable outcome-source identifiers.

## Attribution

Active return versus the best original realized alternative is decomposed into:

- **selection** — the recommended weight times the return spread visible from the decision price;
- **sizing** — the effect of implementing a different weight than the CIO recommendation;
- **timing** — the return difference between decision price and paper implementation price; and
- **implementation cost** — realized transaction cost and slippage.

These components must reconcile exactly to net active portfolio contribution.

The evaluation reports excess return against cash, the benchmark, the passive portfolio, and the best original alternative.

## Process and outcome remain separate

A disciplined decision may lose money. A flawed decision may make money.

Process is marked flawed only when an enforceable governance rule was violated, including:

- acting through an unresolved evidence veto;
- increasing exposure despite an implementation block;
- owning an asset without an explicit thesis; or
- approving a candidate that did not exceed the strongest expected capital alternative.

Outcome is classified independently. Implemented decisions can add value, destroy value, or match the alternative. Inaction is classified as correct abstention, avoided loss, missed opportunity, confirmed insufficient evidence, a costly implementation block, or review timing that was too slow.

## Calibration and learning separation

The evaluator measures distinct questions with distinct diagnostics:

- forecast Brier score — whether the candidate beat the original governing alternative;
- scenario log score — how plausible the realized return was under the reconciled distribution;
- decision-confidence Brier score — whether confidence was justified by decision value added;
- sizing efficiency — value gained or lost by implementing a different weight;
- timing efficiency — value gained or lost between decision and implementation; and
- abstention value — value preserved or forgone by not allocating.

`ConfidenceCalibrator` aggregates frozen confidence without recalculating historical decisions using newer models.

## Walk-forward and universe integrity

`WalkForwardAuditor` rejects:

- model inputs unavailable at the decision timestamp;
- training and evaluation windows that overlap; and
- symbols that were not members of the eligible universe at the decision timestamp.

Point-in-time universe membership must include delisted and later-ineligible securities when they were genuinely available, preventing survivorship-biased evaluation.

## Paper implementation

`PaperTradeFill` measures completion, delay, fill price, slippage, and realized cost against a construction proposal. It is explicitly simulated and cannot be represented as broker execution.

Construction results, evidence snapshots, evaluations, calibration reports, walk-forward audits, and paper fills are written to the same append-only hash-chained CIO journal.
