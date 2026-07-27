# Governed Forecast Evidence

## Authority boundary

Forecasts are supporting evidence. They are not a candidate generator, ranking engine, specialist, CIO, portfolio-construction policy, sizing input, or execution authority.

Every record permanently states:

```text
supporting_only = true
independent_decision_authority = false
```

A candidate may reference a forecast only after complete-universe screening has independently qualified that candidate. The reference can enrich the immutable evidence manifest; it cannot add, remove, rerank, resize, or recommend the candidate.

## Required contract

`GovernedForecastEvidence` preserves:

- forecast target;
- as-of timestamp;
- exact knowledge cutoff;
- generation timestamp;
- horizon end and computed horizon length;
- mutually exclusive scenario names and probabilities that sum to one;
- confidence;
- calibration method;
- calibration sample size;
- historical accuracy measured under the stated method;
- model versions;
- data-vintage versions;
- evidence identifiers;
- originating economic fact identifiers;
- limitations; and
- invalidation conditions.

A forecast generated after the decision, or using evidence after the decision cutoff, cannot enter the production context.

## Candidate references

`CandidateForecastSupport` binds one or more forecast identifiers to:

- one completed screening cycle;
- one already-qualified candidate;
- the exact decision timestamp;
- the exact knowledge cutoff;
- a rationale explaining how the forecast supports specialist analysis; and
- explicit limitations.

`ForecastSupportingProductionContextProvider` wraps the canonical production-context adapter. The delegate assembles the candidate set, opportunity ranking, specialist inputs, portfolio, and immutable manifest first. The wrapper then:

1. verifies both append-only stores;
2. rejects references outside the qualified candidate set;
3. loads each exact forecast record;
4. enforces decision timestamp and cutoff usability;
5. rejects conflicting source or model versions; and
6. adds only forecast, evidence, originating-fact, model, and data identities to the manifest.

When no references exist, the canonical context is returned unchanged.

## Persistence

Two append-only SHA-256 chains are active:

- `SQLiteForecastEvidenceStore` for forecast records;
- `SQLiteCandidateForecastSupportStore` for candidate references.

Updates and deletes are prohibited. Exact replay is idempotent; conflicting content under an existing identifier fails.

## Command

Record a reviewed forecast:

```bash
python run_forecast_evidence.py --forecast artifacts/forecast.json
```

Record a candidate reference after screening:

```bash
python run_forecast_evidence.py \
  --candidate-support artifacts/candidate-forecast-support.json
```

Inspect the latest usable forecast for a target and cutoff:

```bash
python run_forecast_evidence.py \
  --latest-target "global real GDP growth" \
  --knowledge-cutoff 2026-07-27T11:55:00+00:00
```

## Recovery and readiness

Forecast and candidate-reference databases are required active backup authorities. A paper-test baseline must prove that referenced forecasts, calibration evidence, data vintages, and originating-fact lineage can be restored and reconstructed.

A forecast record does not certify a provider, approve an asset class, create a performance claim, or authorize real money.
