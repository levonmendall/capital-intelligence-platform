# Versioned Multi-Engine Synthesis Weights

## Purpose

PR35 applies one explicit fixed-weight policy to the seven normalized analytical
engine assessments created by `multi-engine-normalization.v1`.

The output contains four separate institutional dimensions:

- aggregate opportunity;
- aggregate risk;
- aggregate confidence; and
- aggregate data quality.

It does not create a market stance, recommendation, veto, committee decision,
Personal CIO action, Capital Intelligence Score change, allocation, or order.

## Policy identity

The first policy is `multi-engine-synthesis-weights.v1`. Every policy records:

- publication timestamp;
- opportunity, risk, and evidence weights for every engine;
- minimum weighted coverage for each dimension;
- minimum available-engine count;
- missing-weight behavior;
- whether weights are regime-sensitive; and
- the rationale for the policy version.

Weights use integer basis points. Each policy dimension must total exactly
10,000 basis points.

## Fixed v1 weights

| Engine | Opportunity | Risk | Evidence |
|---|---:|---:|---:|
| Global Liquidity | 20% | 10% | 15% |
| Business Cycle | 20% | 10% | 15% |
| Credit Cycle | 15% | 20% | 15% |
| Market Breadth | 15% | 10% | 15% |
| Valuation | 10% | 10% | 10% |
| Technical and Momentum | 10% | 15% | 10% |
| Risk | 10% | 25% | 20% |

The first policy is intentionally fixed and not regime-sensitive. Dynamic
weights require a later independently versioned policy and historical
validation.

## Coverage and missing weight

A synthesis requires:

- at least five available engines;
- at least 70% opportunity-weight coverage;
- at least 70% risk-weight coverage; and
- at least 70% evidence-weight coverage.

Missing engine weight is never silently assigned to another engine. Every
result reports the unavailable engines and unallocated basis points.

When the thresholds are met with partial evidence, opportunity and risk are
calculated from the observed policy weight. Confidence and data quality remain
penalized by the missing evidence weight. The result is labeled `partial`.

When any threshold is not met, the result is `insufficient_evidence` and no
aggregate scores are published.

## Result statuses

- `complete` — all seven engines are available and all scores are published;
- `partial` — governed coverage thresholds are met with disclosed missing
  engines; or
- `insufficient_evidence` — thresholds are not met and aggregate scores are
  withheld.

## Persistence

The existing `analytical_engines.db` receives two append-only tables:

- `multi_engine_synthesis_policies`; and
- `multi_engine_synthesis_results`.

Policies and results cannot be updated or deleted. Identical retries are
idempotent. A result cannot be stored before its policy version.

## Scheduler order

The durable daily worker performs:

1. seven analytical engines;
2. canonical daily intelligence;
3. raw analytical persistence;
4. multi-engine normalization;
5. weighted synthesis persistence; and
6. the existing selective-alert process.

The canonical daily-cycle return contract remains unchanged.

## API

Authenticated read-only endpoints:

```text
GET /v1/synthesis/latest
GET /v1/synthesis/history?limit=30
GET /v1/synthesis/policies/latest
GET /v1/synthesis/policies/history?limit=30
```

## Historical runner

```bash
python run_synthesis.py
```

To use the latest normalization bundle available at a historical timestamp:

```bash
python run_synthesis.py --as-of 2026-01-31T21:00:00Z --no-persist
```

## Explicit non-authority boundary

Every result reports:

```json
{
  "weights_applied": true,
  "missing_weights_redistributed": false,
  "veto_policy_applied": false,
  "committee_submitted": false,
  "market_stance": null,
  "personal_cio_action_affected": false,
  "capital_intelligence_score_affected": false
}
```

PR36 remains responsible for broader missing-data, conflict, confidence-ceiling,
and veto policy. Later PRs remain responsible for committee governance, shadow
validation, and any Capital Intelligence Score activation.
