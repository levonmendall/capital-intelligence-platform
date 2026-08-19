# Capability-Based Paper Eligibility

The portfolio does not treat the original 15-instrument registry as its permanent ownership ceiling. Those instruments remain active bootstrap certifications and regression anchors. Additional classified liquid instruments may become paper-allocatable through a complete, active, point-in-time instrument certification.

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
- asset-family lifecycle capabilities required by the Universal Capability Graph

Certification does not compel ownership. It only permits the instrument to progress from research into CIO-authorized paper construction. The opportunity engine, six-specialist committee, CIO, portfolio construction engine, implementation controls, and reconciliation remain independent gates.

## Production promotion path

The Universal Capability Graph is now part of the production paper-authority path rather than a shadow-only design.

```text
complete global discovery
  -> qualified point-in-time screening candidate
  -> ProductionCapabilityAuthority
  -> InstrumentCapabilityEvidence
  -> Universal Capability Graph evaluation
  -> AutomaticInstrumentEligibilityFactory.reconcile()
  -> append-only exact instrument certification or suspension
  -> production CIO membership gate
  -> CIO / construction
  -> universal paper-order lifecycle invariant
  -> canonical multi-asset paper ledger and reconciliation
```

`production_context_publication_runtime.py` reconciles the completed screening publication only after the exact active universe has been durably published. Provider visibility, configuration defaults, or an apparently complete profile are insufficient. A dynamic instrument must have a complete capability graph backed by the exact qualified screening evidence for the decision timestamp.

The factory is also a revocation path. If required evidence, liquidity, lifecycle proof, or active-universe membership degrades, a suspension is appended rather than mutating prior authority.

## Authority sequence

1. Broad screening may observe and evaluate any classified market instrument.
2. Complete decision evidence may promote an instrument into the governed screening candidate set.
3. The production capability evidence owner evaluates the exact structural instrument and its operational stack.
4. A complete graph may append an active `InstrumentPaperEligibilityCertification`; an incomplete or degraded graph cannot.
5. At the exact production decision timestamp, bootstrap instruments or actively certified dynamic instruments may reach committee/CIO ownership consideration.
6. The CIO may approve, reject, watch, reduce, or exit the instrument.
7. Portfolio construction applies the certification's maximum weight together with portfolio-wide constraints.
8. New/increased paper exposure must satisfy the universal asset-family paper-order contract at the fill boundary.
9. Existing owned positions retain reduction/exit continuity if a certification is later suspended, but suspended authority cannot create or increase exposure.
10. Canonical paper accounting and reconciliation remain fail-closed and real-money routing remains prohibited.

## Asset-family lifecycle proof

The universal graph requires common capabilities plus structure-specific proof:

- equities/funds: corporate actions, exchange session, settlement cycle
- direct fixed income: maturity terms, coupon accrual, duration model, bond settlement
- futures: expiry, roll model, multiplier, initial and maintenance margin
- options: strike/side/expiry, multiplier, exercise/assignment, Greeks model, option margin
- FX: pair convention, financing, rollover, settlement
- crypto: continuous session, denomination, venue model, custody simulation

Listed wrappers are evaluated by their actual execution structure. A bond ETF, for example, is structurally a fund even though its economic exposure is fixed income. Direct bonds remain fail-closed until actual bond terms and the complete lifecycle stack are available.

## Universal paper execution contract

The CIO and construction engine express economic target exposure. The paper execution boundary translates that target according to structural asset family:

- equities/funds -> shares
- fixed income -> face-value units
- futures/options -> contracts
- FX -> base-currency units
- crypto -> asset units

The existing multi-asset paper ledger remains authoritative for session checks, quotes, liquidity, cash, positions, fills, accounting, and reconciliation. The universal contract is an additional authoritative invariant: a generated fill must reconcile to the normalized asset-family instruction. Direct fixed-income percentage-of-par quotes are normalized for ledger accounting while retaining the market convention for independent face-value reconciliation.

## Fail-closed behavior

New or increased paper authority is removed when any of the following applies:

- certification is missing, expired, suspended, or revoked
- the current published universe omits an actively certified dynamic instrument
- symbol, asset class, venue, country, or instrument type differs from the certification
- current qualified screening liquidity falls below the certified floor
- leverage exceeds the certified limit
- a required common or asset-family lifecycle capability is missing
- the append-only certification chain fails integrity verification

Loss of new-exposure authority does not trap an existing position. The canonical execution path may still reduce or exit an exactly reconciled owned instrument while preventing any increase.

## Storage and reporting

Individual certifications are stored in the append-only, hash-chained SQLite authority at:

`database/instrument-paper-eligibility.db`

The path may be overridden with:

`CAPITAL_INTELLIGENCE_INSTRUMENT_PAPER_ELIGIBILITY_DATABASE`

The latest production reconciliation report is written alongside canonical portfolio state as:

`production-capability-authority.json`

Creating a database does not authorize an instrument. A complete certification record must be appended and active at the decision timestamp. The existing market registry remains the monitoring taxonomy and bootstrap authority; it is no longer the sole mechanism for adding paper-allocatable instruments.

## Non-authority

This design does not:

- authorize live money
- lower evidence, expected-return, downside, liquidity, or cash-hurdle thresholds
- allow unclassified instruments
- allow a data provider, UI, forecast, specialist, capability graph, or execution adapter to issue a CIO action
- allow a capability certification to compel ownership
- bypass CIO authority, construction, implementation, or reconciliation
