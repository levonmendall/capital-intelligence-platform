# Legacy Authority Isolation

## Purpose

The repository retains some historical modules and data stores for migration, offline comparison, and regression evidence. They are not part of the active investment authority graph.

The active graph is:

```text
complete-universe publication
    -> CandidateDecisionRecord
    -> OpportunityEngine
    -> independent specialists
    -> ChiefInvestmentOfficer
    -> PortfolioConstructionEngine
    -> canonical append-only portfolio state
    -> LivingThesis
    -> DecisionEvidenceSnapshot
    -> PointInTimeDecisionEvaluator
```

The active investment mandate is `COMPOUNDING`. Liquidity, concentration, leverage, turnover, cash, cost, and restricted-exposure rules are implementation constraints, not alternate mandates.

## Isolated legacy areas

The following may remain in the repository but must not be imported, registered, seeded, or treated as current state by active application, API, scheduler, construction, paper-execution, alert, backup, or reporting entrypoints:

- `personal_cio/`;
- `personalization/`;
- `api/routes/personal.py`;
- Investor Memory implementations and historical stores;
- conviction-trend reporting and API implementations;
- goal and investment-policy compatibility modules;
- score-first daily reporting;
- weighted-voter committee and consensus engines;
- legacy recommendation or snapshot-decision fallbacks;
- the retired mandate/trading database except as a query-only migration source; and
- preservation, income, balanced, growth, tactical, value, global, and innovation mandate labels except in historical migration evidence.

## Permitted use

Legacy code and data may be used only for:

- reading historical migration records offline;
- comparing old and canonical outputs in controlled research;
- preserving backward-compatible database restoration; or
- supporting tests that prove the old authority is isolated.

It may not:

- qualify or rank candidates;
- alter opportunity cost;
- participate in canonical specialist packets;
- issue a CIO action or confidence;
- determine position size or funding;
- own active cash, holdings, valuations, or implementation lineage;
- change thesis state;
- trigger investment alerts;
- create a competing portfolio objective; or
- appear as the default user-facing decision.

## Score and alert boundary

The Capital Intelligence Score is deprecated diagnostic context. It is not expected return, an opportunity rank, CIO confidence, a position size, or a trading signal. The active Today surface and `/v1/cio/*` API do not depend on it.

The active alert system accepts only `cio_decision`, `thesis`, `opportunity`, `implementation`, `evidence`, and `daily_briefing` topics. Legacy score, conviction, confidence-threshold, goal, and mandate-change alert controls may decode archived records only; they cannot create an active delivery.

## Enforcement

Static architecture tests inspect active entrypoints for prohibited imports, route registration, parallel portfolio-state ownership, and score-first wording. Integration tests prove that old identity grants cannot reactivate retired endpoints. The canonical API reads only persisted CIO journal and canonical portfolio records and returns no synthetic fallback.

## Retirement criteria

A legacy module or store may be deleted when:

- historical data has been migrated or archived;
- backup and restore no longer require its schema;
- no supported offline research workflow depends on it; and
- architecture tests confirm no active import path remains.
