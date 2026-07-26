# Legacy Authority Isolation

## Purpose

The repository retains some historical modules and data stores for migration, offline comparison, and regression evidence. They are not part of the active investment authority graph.

The active graph is:

```text
CandidateDecisionRecord
    -> OpportunityEngine
    -> independent specialists
    -> ChiefInvestmentOfficer
    -> PortfolioConstructionEngine
    -> LivingThesis
    -> DecisionEvidenceSnapshot
    -> PointInTimeDecisionEvaluator
```

## Isolated legacy areas

The following may remain in the repository but must not be imported or registered by active application, API, or canonical-cycle entrypoints:

- `personal_cio/`;
- `personalization/`;
- `api/routes/personal.py`;
- Investor Memory implementations and historical stores;
- conviction-trend reporting and API implementations;
- goal and investment-policy compatibility modules;
- score-first daily reporting;
- weighted-voter committee and consensus engines; and
- legacy recommendation or snapshot-decision fallbacks.

## Permitted use

Legacy code may be used only for:

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
- change thesis state;
- trigger investment alerts; or
- appear as the default user-facing decision.

## Score boundary

The Capital Intelligence Score is deprecated diagnostic context. It is not expected return, an opportunity rank, CIO confidence, a position size, or a trading signal. The active Today surface and `/v1/cio/*` API do not depend on it.

## Enforcement

Static architecture tests inspect active entrypoints for prohibited imports, route registration, and score-first wording. Integration tests prove that old identity grants cannot reactivate retired endpoints. The canonical API reads only persisted CIO journal records and returns no synthetic fallback.

## Retirement criteria

A legacy module may be deleted when:

- historical data has been migrated or archived;
- backup and restore no longer require its schema;
- no supported offline research workflow depends on it; and
- architecture tests confirm no active import path remains.
