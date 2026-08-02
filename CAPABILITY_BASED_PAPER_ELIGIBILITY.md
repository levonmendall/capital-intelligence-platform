# Capability-Based Paper Eligibility

The portfolio no longer treats the current 15-instrument registry as its permanent ownership ceiling. Those instruments remain active bootstrap certifications for the bounded pilot. Additional classified liquid instruments may become paper-allocatable through a complete, active, point-in-time instrument certification.

## Ownership rule

An instrument may enter paper portfolio construction only when all of the following are certified for that exact instrument:

- market data and point-in-time availability
- stable identity, listing, venue, country, and instrument structure
- decision evidence coverage
- valuation and expected-return model applicability
- trading calendar and market-session behavior
- current liquidity and a certified minimum dollar-volume floor
- transaction-cost and participation-rate models
- accounting treatment
- custody and settlement representation
- paper execution model
- portfolio construction compatibility
- risk model, leverage boundary, and instrument-level position cap
- an applicable asset-class approval

Certification does not compel ownership. It only permits the instrument to progress from research into CIO-authorized paper construction. The opportunity engine, six-specialist committee, CIO, portfolio construction engine, implementation controls, and reconciliation remain independent gates.

## Authority sequence

1. Broad screening may observe and evaluate any classified market instrument.
2. Complete decision evidence may promote an instrument to committee and CIO consideration.
3. An active `InstrumentPaperEligibilityCertification` may promote the exact instrument to paper-allocation eligibility.
4. The CIO may approve, reject, watch, reduce, or exit the instrument.
5. Portfolio construction applies the certification's maximum weight together with portfolio-wide constraints.
6. Paper execution remains fail-closed and real-money routing remains prohibited.

## Fail-closed behavior

Paper authority is removed when any of the following applies:

- certification is missing, expired, suspended, or revoked
- the published universe omits an actively certified instrument
- symbol, asset class, venue, country, or instrument type differs from the certification
- current average daily dollar volume falls below the instrument-specific certified floor
- leverage exceeds the certified limit
- the append-only certification chain fails integrity verification

## Storage

Individual certifications are stored in the append-only, hash-chained SQLite authority at:

`database/instrument-paper-eligibility.db`

The path may be overridden with:

`CAPITAL_INTELLIGENCE_INSTRUMENT_PAPER_ELIGIBILITY_DATABASE`

Creating a database does not authorize an instrument. A complete certification record must be appended and active at the decision timestamp. The existing market registry remains the monitoring taxonomy and bootstrap authority; it is no longer the sole mechanism for adding paper-allocatable instruments.

## Non-authority

This design does not:

- authorize live money
- lower evidence, expected-return, downside, liquidity, or cash-hurdle thresholds
- allow unclassified instruments
- allow a data provider, UI, forecast, specialist, or execution adapter to authorize a trade
- bypass CIO authority, construction, implementation, or reconciliation
