# Multi-Engine Evidence Governance

## Purpose

PR36 adds the governed layer between weighted multi-engine measurement and future
committee judgment. It determines whether the institutional evidence set is
usable, incomplete, stale, materially conflicted, or constrained by a credit or
risk veto.

The layer does **not** change the opportunity, risk, confidence, or data-quality
scores produced by `multi-engine-synthesis-weights.v1`. It records those scores
unchanged and applies only a disclosed confidence ceiling and conclusion
constraint.

The policy is `multi-engine-governance.v1`.

## Separation of responsibilities

The institutional sequence is now:

1. raw analytical engines;
2. per-engine normalization;
3. fixed weighted synthesis;
4. evidence governance; and
5. future committee submission.

PR36 owns step four only. It does not create a market stance, approve a
recommendation, alter a Personal CIO action, change the Capital Intelligence
Score, mutate a portfolio, or execute a transaction.

## Governance outcomes

A result has one status:

- `cleared` — evidence meets the policy without a material governance issue;
- `incomplete` — evidence remains usable but missing or incomplete inputs reduce
  conviction;
- `stale` — stale evidence lowers the maximum permitted confidence;
- `conflicted` — material supportive and adverse evidence disagree;
- `vetoed` — confirmed credit or risk stress blocks a high-conviction positive
  conclusion; or
- `decision_unavailable` — the weighted synthesis or evidence quality is below a
  hard minimum, so no institutional conclusion is available.

A veto is not a sell instruction. It does not require a hedge, allocation
change, transaction, or portfolio response. It only limits the strength of a
future positive conclusion until the triggering condition is resolved or a
versioned policy changes.

## Default policy

`multi-engine-governance.v1` records:

- preferred aggregate confidence: 50;
- preferred aggregate data quality: 60;
- hard aggregate confidence minimum: 30;
- hard aggregate data-quality minimum: 40;
- aggregate opportunity/risk conflict threshold: 65/65;
- engine-level support/risk threshold: 65;
- minimum two supportive and two adverse engines for cross-engine conflict;
- credit veto risk threshold: 75;
- risk veto risk threshold: 75;
- minimum veto confidence and data quality: 50;
- incomplete confidence ceiling: 65;
- stale confidence ceiling: 60;
- critical credit/risk stale or unavailable ceiling: 45;
- conflict confidence ceiling: 55; and
- veto confidence ceiling: 50.

Credit Cycle and Risk are the first critical engines. Their absence or staleness
blocks high-conviction positive conclusions but does not fabricate a negative
stance.

## Missing data

PR35 remains responsible for minimum weighted coverage and engine-count
thresholds. If PR35 returns `insufficient_evidence`, PR36 returns
`decision_unavailable` and publishes no governed confidence.

If PR35 permits a partial synthesis, PR36:

- preserves the original aggregate scores;
- records incomplete and unavailable engines;
- keeps missing weight unallocated;
- applies a confidence ceiling; and
- requires human review.

## Conflict policy

Conflict is recognized when either:

- aggregate opportunity and aggregate risk are both at least 65; or
- at least two material engines are supportive and at least two material engines
  are adverse.

A conflicted result remains available for committee review, but high-conviction
positive conclusions are blocked and governed confidence cannot exceed 55.

## Credit and risk vetoes

A veto requires all of the following for the relevant engine:

- a normalized risk score at or above the versioned threshold;
- source direction of `contracting` or `stressed`;
- confidence of at least 50; and
- data quality of at least 50.

This confirmation requirement prevents a low-quality or isolated signal from
creating a veto.

The result records:

- veto type;
- triggering engine;
- normalized assessment identifier;
- source direction;
- risk, confidence, and data-quality scores; and
- a plain-language reason.

## Confidence ceilings

PR36 does not rewrite source confidence. It publishes:

- the original aggregate confidence from PR35;
- the applicable policy ceiling; and
- governed confidence equal to the lower of the two.

Multiple issues use the strictest applicable ceiling.

## Formal no-action default

Until future committee governance explicitly approves a conclusion, every PR36
result records:

```json
{
  "unapproved_action_default": "no_action",
  "committee_submitted": false,
  "market_stance": null,
  "personal_cio_action_affected": false,
  "capital_intelligence_score_affected": false,
  "portfolio_mutation_authority": false,
  "transaction_authority": false
}
```

This is an institutional authorization boundary, not an investor-specific
recommendation.

## Persistence

PR36 adds append-only tables to `analytical_engines.db`:

- `multi_engine_governance_policies`;
- `multi_engine_governance_results`.

Updates and deletes are prevented. Identical retries are idempotent. Conflicting
content for the same policy version or decision timestamp is rejected. A result
cannot be stored until its policy version has been appended.

The existing encrypted backup process already includes this database.

## API

Authenticated read-only endpoints:

```text
GET /v1/governance/latest
GET /v1/governance/history?limit=30
GET /v1/governance/policies/latest
GET /v1/governance/policies/history?limit=30
```

No write route is exposed.

## Command line

Evaluate the latest stored normalization and synthesis:

```bash
python run_governance.py
```

Historical point-in-time evaluation without persistence:

```bash
python run_governance.py \
  --as-of 2026-01-31T21:00:00Z \
  --no-persist
```

## Validation expectations

Tests must cover:

- cleared evidence;
- partial noncritical evidence;
- missing critical engines;
- stale critical evidence;
- aggregate and engine-level conflict;
- confirmed credit veto;
- confirmed risk veto;
- low-confidence stress that cannot trigger a veto;
- decision unavailability;
- immutable policy and result persistence;
- scheduler sequencing;
- unchanged canonical daily return behavior; and
- read-only API access.
