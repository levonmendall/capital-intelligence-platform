# Multi-Engine Normalization Contract

## Purpose

The platform now has seven independent analytical engines:

1. Global Liquidity
2. Business Cycle
3. Credit Cycle
4. Market Breadth
5. Valuation
6. Technical and Momentum
7. Risk

Those engines share a transport contract, but their native scores do not
automatically have identical investment meaning. `multi-engine-normalization.v1`
creates a disclosed translation layer without combining the engines or creating
a market conclusion.

## Boundaries

This contract performs:

- explicit engine-role declaration;
- native-score orientation declaration;
- opportunity and risk translation for each engine independently;
- confidence adjustment for coverage and evidence quality;
- data-quality scoring;
- evidence freshness disclosure;
- materiality scoring;
- preservation of supporting and contradictory evidence; and
- append-only point-in-time persistence.

This contract does **not** perform:

- cross-engine weighting;
- missing-weight redistribution;
- veto policy;
- committee submission;
- market stance;
- portfolio recommendation;
- Capital Intelligence Score changes; or
- trade or allocation instructions.

The output explicitly reports:

```json
{
  "aggregation_status": "not_performed",
  "weights_applied": false,
  "veto_policy_applied": false,
  "committee_submitted": false,
  "market_stance": null,
  "aggregate_opportunity_score": null,
  "aggregate_risk_score": null
}
```

## Per-engine assessment

Each normalized assessment retains:

- engine and institutional role;
- source result and source policy identifiers;
- source direction, score, and confidence;
- opportunity score;
- risk score;
- normalized confidence;
- data-quality score;
- source coverage;
- freshness in days;
- materiality score;
- data status;
- supporting evidence identifiers;
- contradictory evidence identifiers; and
- the normalization-policy version.

Unavailable evidence remains unavailable. No opportunity or risk value is
imputed for a missing or explicitly unavailable engine.

## Explicit semantic policies

Every engine has a named role and declared score orientation.

| Engine | Role | Native orientation |
|---|---|---|
| Global Liquidity | System liquidity | Higher is more supportive |
| Business Cycle | Economic growth | Higher is more supportive |
| Credit Cycle | Credit availability | Higher is more supportive |
| Market Breadth | Market participation | Higher is more supportive |
| Valuation | Valuation support | Higher is more supportive |
| Technical and Momentum | Price confirmation | Higher is more supportive |
| Risk | Market resilience | Higher is more supportive |

The shared orientation is a declared property of the current seven policies,
not an undocumented assumption. A future engine with inverse semantics must
declare `lower_is_supportive`.

## Translation

For an available engine:

1. Orient the native score so higher always means more support.
2. Blend 70% of the oriented native score with 30% of a disclosed direction
   anchor:
   - expanding: 80
   - neutral: 50
   - contracting: 25
   - stressed: 10
3. Set risk to the exact complement of opportunity.
4. Adjust source confidence by coverage and normalized data quality.
5. Calculate materiality from distance from neutral, adjusted confidence, and
   no cross-engine weights.

These calculations make one engine's fields comparable with another engine's
fields. They do not say how important one engine should be relative to another.

## Data quality

Data-quality scoring combines:

- engine status: current, incomplete, stale, or unavailable; and
- evidence states: live, cached, fixture, fallback, stale, or missing.

The original status and evidence identifiers remain available for audit. A
numeric data-quality score is a translation aid, not permission to ignore the
underlying provenance.

## Evidence disagreement

Supporting and contradictory evidence are retained relative to the source
engine's own direction.

- Expanding results treat positive signals as supporting and negative signals
  as contradictory.
- Contracting or stressed results use the inverse.
- Neutral results treat small signals as support for neutrality and strong
  directional signals as disagreement.

No disagreement penalty or veto is applied in this PR.

## Persistence

Normalization bundles are stored in the existing
`analytical_engines.db` database in an append-only table:

```text
multi_engine_normalization_bundles
```

The table prevents updates and deletes. Repeating an identical decision-time
run is idempotent. Different content for the same decision timestamp is
rejected.

The scheduler writes raw engine results first and then writes one normalization
bundle. The canonical daily-cycle return contract remains unchanged.

## API

Authenticated read-only endpoints:

```text
GET /v1/normalization/latest
GET /v1/normalization/history?limit=30
```

No write route is exposed.

## Command line

Normalize the latest engine results available at the current time:

```bash
python run_normalization.py
```

Normalize a historical decision timestamp without persistence:

```bash
python run_normalization.py \
  --as-of 2026-01-31T21:00:00Z \
  --no-persist
```

## Next governed step

The next policy may assign versioned cross-engine weights. That policy must be
implemented separately so normalization remains stable, auditable, and
independent of later investment-committee preferences.
