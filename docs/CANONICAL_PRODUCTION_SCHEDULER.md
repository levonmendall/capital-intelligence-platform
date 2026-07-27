# Canonical Production Scheduler

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The production scheduler has one investment-decision authority: `CanonicalCIOCycle`.

## Evidence boundary

Each scheduled cycle requires a complete persisted publication from the full-universe screening ledger. Candidates are reconstructed from that immutable publication. An external context provider supplies only:

- the matching opportunity-set context;
- independent specialist contexts;
- the current canonical portfolio state; and
- the deployed code version.

The provider cannot add, remove, replace, or mutate candidates. The executor rejects missing publications, incomplete coverage, candidate-count mismatches, mismatched opportunity-context identifiers, timestamp disagreements, and invalid screening or CIO-journal chains.

## Configuration

```bash
export CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE=database/full_universe_screening.db
export CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER=production_context:create_provider
python run_scheduler.py
```

The context-provider factory must take no arguments and return an object exposing:

```python
name: str
load_context(*, as_of: datetime) -> ProductionCanonicalCIOContext
```

There is no default provider and no fallback to the retired daily snapshot, regime, weighted-engine synthesis, score, or conviction pipeline.

## Durable execution

The worker derives one key per configured market date, claims it transactionally in the alert operations database, and records completed or failed status. A completed claim stores the canonical daily briefing identifier. Failures receive a bounded retry time and preserve the error. Exact replay cannot create a second completed daily cycle.

Delivery draining remains operationally separate from investment analysis. Canonical event generation is governed by the alert domain and cannot alter the CIO result.
