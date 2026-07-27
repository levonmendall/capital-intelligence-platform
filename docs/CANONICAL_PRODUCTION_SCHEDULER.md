# Canonical Production Scheduler

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The production scheduler has one investment-decision authority: `CanonicalCIOCycle`.

## Evidence boundary

Each scheduled cycle requires three persisted, integrity-valid authorities at the exact decision timestamp:

1. a complete full-universe screening publication;
2. an append-only canonical portfolio snapshot; and
3. a certified production-context evidence snapshot.

`RepositoryProductionCanonicalCIOContextProvider` assembles the context from those records. It reconstructs the immutable screened candidates, loads current cash and holdings, creates cash and holding alternatives, adds the persisted qualified candidates as peer alternatives, builds one specialist context and one exposure profile for every qualified candidate, and preserves the complete evidence, source-version, and model-version lineage in a `ProductionContextManifest`.

The provider fails closed when timestamps or knowledge cutoffs disagree; candidate or holding coverage is missing or duplicated; evidence is stale, uncertified, rejected, conditional, or expired; exposure profiles are missing; an equity candidate lacks governed fundamental and valuation analysis; the portfolio snapshot is absent; or any append-only chain is invalid.

The provider cannot add, remove, replace, mutate, or silently re-screen candidates. The executor independently reconstructs the candidate set from the screening publication and verifies the provider manifest against the persisted qualified queue before starting `CanonicalCIOCycle`.

## Repository-default configuration

The repository-owned provider is the scheduler default. No context-provider environment variable is required.

```bash
export CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE=database/full_universe_screening.db
export CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE=database/canonical_portfolio.db
export CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE=database/production_context.db
export CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE=COMPOUNDING
python run_scheduler.py
```

An explicit `CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER=module:function` may still be supplied for controlled deployments. The factory must take no arguments and return an object exposing:

```python
name: str
load_context(*, as_of: datetime) -> ProductionCanonicalCIOContext
```

An override remains subject to the executor's persisted-publication, timestamp, candidate-count, opportunity-context, and manifest checks. There is no fallback to the retired daily snapshot, regime, weighted-engine synthesis, score, conviction, goal, or mandate pipeline.

## Persisting production context evidence

Upstream governed operations append one `ProductionContextEvidenceSnapshot` per portfolio and decision timestamp to `SQLiteProductionContextStore`. The snapshot contains:

- the screening-cycle identifier and knowledge cutoff;
- certified cash evidence;
- governed macro and market evidence;
- fundamental and valuation evidence where required;
- candidate exposure profiles;
- governed current-holding expected returns, costs, liquidity, and exposures;
- certification identifiers and expiry;
- evidence freshness boundaries;
- source versions; and
- model versions.

The context store is append-only, hash-chained, idempotent by snapshot identifier, and rejects update or delete operations.

## Durable execution

The worker derives one key per configured market date, claims it transactionally in the alert operations database, and records completed or failed status. A completed claim stores the canonical daily briefing identifier. Failures receive a bounded retry time and preserve the error. Exact replay cannot create a second completed daily cycle.

Delivery draining remains operationally separate from investment analysis. Canonical event generation is governed by the alert domain and cannot alter the CIO result.
