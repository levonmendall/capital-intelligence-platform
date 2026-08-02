# Merit-Based Market Discovery

Each scheduled lane reads its complete configured catalog, applies cheap metadata,
freshness, lifecycle, and basic-liquidity checks, and forms independent quality, value,
momentum, carry, diversification, and improving-condition sleeves. Sleeves are merged
round-robin and deduplicated before the 200-candidate deep-analysis limit is applied.

Current holdings and tracked instruments are handled through a separate continuity
allocation, so they never consume the 200 new-opportunity slots. A below-cutoff shadow
cohort and baseline prices are published, allowing later cycles to compare its returns
with the selected cohort.

## Provider-enriched factors are mandatory

The canonical runtime no longer permits the value, momentum, carry, or
improving-conditions sleeves to be populated from catalog completeness, symbol order,
spread metadata, deterministic tie-breaking, or another synthetic proxy.

Before comprehensive discovery runs, the provider pipeline must publish
`database/provider-enriched-preselection.json` or set
`CAPITAL_INTELLIGENCE_PROVIDER_PRESELECTION_PATH` to another governed publication.
The publication must use schema
`capital-intelligence-provider-preselection.v1` and contain, for every eligible
new-opportunity candidate:

- a normalized score between zero and one for value, momentum, carry, and improving
  conditions;
- the underlying finite raw measurement and its units;
- the measurement horizon;
- provider identity and methodology version;
- point-in-time observation and availability timestamps; and
- one or more immutable provider evidence identifiers.

The loader creates factor-specific lineage identifiers and carries them into the lane
manifest. A score without factor-specific provider lineage is treated as unavailable.
A missing, stale, future-known, malformed, or incomplete publication makes the affected
candidate ineligible before the 200-candidate cutoff. The system does not substitute a
neutral score and does not lower an investment threshold to preserve candidate count.

A minimal publication has this shape:

```json
{
  "schema_version": "capital-intelligence-provider-preselection.v1",
  "available_at": "2026-08-01T14:59:00+00:00",
  "source_identifiers": ["provider-publication:example:1"],
  "signals": {
    "ABC": {
      "observed_at": "2026-08-01T14:58:00+00:00",
      "eligible": true,
      "liquidity_score": 0.95,
      "quality_score": 0.82,
      "indicative_price": 100.0,
      "source_identifiers": ["provider-signal:ABC"],
      "factors": {
        "value": {
          "score": 0.78,
          "raw_value": 0.071,
          "units": "earnings-yield",
          "horizon_days": 365,
          "provider": "licensed-provider",
          "methodology_version": "equity-value.v1",
          "observed_at": "2026-08-01T14:55:00+00:00",
          "evidence_identifiers": ["fundamentals:ABC:2026Q2"]
        },
        "momentum": {
          "score": 0.69,
          "raw_value": 0.124,
          "units": "total-return",
          "horizon_days": 126,
          "provider": "licensed-provider",
          "methodology_version": "cross-sectional-momentum.v1",
          "observed_at": "2026-08-01T14:55:00+00:00",
          "evidence_identifiers": ["prices:ABC:2026-08-01"]
        },
        "carry": {
          "score": 0.61,
          "raw_value": 0.032,
          "units": "annualized-yield",
          "horizon_days": 365,
          "provider": "licensed-provider",
          "methodology_version": "asset-specific-carry.v1",
          "observed_at": "2026-08-01T14:55:00+00:00",
          "evidence_identifiers": ["income:ABC:2026-08-01"]
        },
        "improving_conditions": {
          "score": 0.84,
          "raw_value": 0.19,
          "units": "standardized-change",
          "horizon_days": 90,
          "provider": "licensed-provider",
          "methodology_version": "improving-conditions.v1",
          "observed_at": "2026-08-01T14:55:00+00:00",
          "evidence_identifiers": ["revisions:ABC:2026-08-01"]
        }
      }
    }
  }
}
```

The factor methodology is asset-specific. Equity value can use normalized earnings or
free-cash-flow yield, while bond, FX, crypto, futures, and option value and carry require
their own governed models. A factor must remain unavailable when an appropriate model or
licensed evidence source does not exist.

Explicit catalog and market probes without a preselection probe remain available only
as deterministic fixture seams for tests and rehearsals. They are not the canonical
production authority path.

Discovery remains nomination-only. It cannot qualify, size, authorize, execute, or
promote an investment. The existing evidence, specialist, CIO, construction, and
paper-only controls remain binding after preselection.
