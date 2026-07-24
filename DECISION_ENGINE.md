# Institutional Decision Engine

## Objective

The decision engine converts independent analytical results into an auditable
institutional conclusion. It does not collapse uncertainty into a single opaque
number, and a high analytical score does not bypass committee or portfolio
constraints.

## Result contract

Every analytical engine returns:

- classification or normalized score;
- component scores;
- confidence;
- data coverage and quality;
- supporting evidence;
- risks and counterarguments;
- missing inputs;
- natural-language explanation derived from structured results;
- rule-set or model version.

## Market factor framework

The initial configurable market framework is:

| Factor | Initial weight |
| --- | ---: |
| Economic regime | 20% |
| Global liquidity | 15% |
| Credit conditions | 15% |
| Business cycle | 10% |
| Market breadth | 10% |
| Valuation | 10% |
| Trend and momentum | 10% |
| Risk conditions | 10% |

These are hypotheses, not validated constants. Weight changes require a
versioned policy and out-of-sample evaluation.

## Separate decision dimensions

The platform reports opportunity, risk, confidence, data-quality, and final
institutional scores separately. Risk-oriented inputs are not inverted or
hidden without disclosure. The final score must show each raw factor, weight,
weighted contribution, confidence adjustment, and applicable policy rule.

## Confidence and missing data

Confidence reflects evidence completeness, signal agreement, signal strength,
and model limitations. Missing data lowers coverage and confidence; it does not
default to neutral unless a versioned policy explicitly says so. Missing core
inputs may block a decision.

## Committee process

1. Analytical engines publish immutable assessments.
2. Committee members form independent opinions within their mandates.
3. The meeting checks quorum and policy versions.
4. Weighted votes, dissent, and conflicts are recorded.
5. Veto rules are evaluated.
6. A final decision is issued with rationale and invalidation conditions.
7. Portfolio policy independently determines whether a position is permissible.

Potential outcomes during development are `Highly attractive`, `Attractive`,
`Neutral`, `Unattractive`, `High risk`, and `Insufficient evidence`.

`No action` is a formal terminal outcome. It records why action is not
warranted, the evidence supporting restraint, what future conditions would
permit action, and when the committee must review the decision.

Material dissent is preserved as a structured minority view rather than
averaged into confidence. Each dissent identifies the conflicting position,
supporting evidence, materiality, and observable conditions that could resolve
the disagreement.

## Thesis and falsification lifecycle

Theses move through proposed, active, challenged, invalidated, and closed
states. Every active thesis has explicit falsification triggers and a review
date. Triggers may reference price, valuation, macro, fundamental,
market-structure, data-quality, or time conditions.

Lifecycle transitions are append-only and require a timestamp and rationale.
Invalidation and closure do not erase the original proposition or evidence.

## Evidence trust

Evidence trust reports source quality, freshness, completeness, point-in-time
integrity, directness, revision stability, and known limitations. The initial
equal-weight score is disclosed and versionable. It informs confidence but
does not replace the underlying dimensions.

## Scenarios and transmission assumptions

Scenarios explicitly name changed factors, direction, magnitude, rationale,
and assumptions. Cross-asset transmission maps record direction, strength,
expected lag, and rationale for relationships such as real yields to growth
equity valuation or liquidity to Bitcoin.

These maps are hypotheses, not causal facts. They require versions and later
out-of-sample evaluation.

## Veto and escalation conditions

Initial policy should permit veto or abstention for:

- insufficient data coverage;
- stale or untraceable core evidence;
- mandate violation;
- unacceptable liquidity or concentration;
- unresolved model disagreement;
- missing thesis-invalidation conditions;
- operational or legal restriction.

Thresholds belong in versioned configuration and require dedicated tests.

## Position sizing boundary

Position size is not a direct transform of the final score. It also requires
confidence, volatility, liquidity, correlation, concentration, mandate limits,
risk budget, drawdown tolerance, and portfolio state. Until those controls are
implemented, outputs are research and paper-trading proposals only.

## Explainability and AI

AI may summarize evidence, compare cases, identify contradictions, and render
structured reports. It may not invent data, alter deterministic scores, hide
missing evidence, override committee policy, or generate unconstrained
allocations. AI-generated prose must be traceable to structured inputs.

## Decision record

Persist the input snapshot, all assessments, votes, dissent, policy and model
versions, final result, invalidation conditions, portfolio response, timestamps,
and code release identifier. Later analytics attach realized outcomes without
rewriting what was known at decision time.

Retrospective reviews separately record process verdict and realized outcome.
The decision-quality ledger classifies disciplined-positive,
disciplined-negative, flawed-positive, and flawed-negative cases, with
unresolved or flat outcomes remaining inconclusive.

The first persisted event schemas are `regime-run.v1` and
`decision-quality-review.v1`. They are stored in the separate institutional
journal with database-level update/delete guards and a tamper-evident hash
chain. Future committee, mandate, and portfolio-response events will extend the
ledger through new schema versions rather than changing prior payloads.
