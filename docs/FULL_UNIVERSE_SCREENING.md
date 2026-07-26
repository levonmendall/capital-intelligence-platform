# Complete Version 1 Universe Screening

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The full-universe orchestrator is the production boundary between an activated point-in-time security master and the opportunity engine. It cannot certify a provider, activate a catalog, invent missing metrics, fill analytical gaps, or publish a partial opportunity set.

## Required sequence

1. Retrieve the currently activated catalog through `SecurityMasterIngestionService.active_catalog()`.
2. Reconstruct the security master at one `as_of` and `knowledge_cutoff` boundary.
3. Require point-in-time liquidity and analytical-coverage metrics for every instrument in that master.
4. Build one immutable `Version1UniverseSnapshot` under the versioned recommendation-universe policy.
5. Screen every eligible constituent in deterministic partitions.
6. Retry failed partitions without rewriting prior attempts or completed results.
7. Publish candidates, exclusions, and the opportunity queue only after exact 100% eligible-instrument coverage.
8. Record the completed terminal cycle for the operational SLO.
9. Append candidate and opportunity-queue evidence to the canonical CIO journal only after publication.

A provider outage, expired certification, stale catalog, missing metric, invalid candidate lineage, exhausted partition retry, unknown instrument, or count mismatch produces a failed terminal cycle and no CIO evidence.

## Resumability

`SQLiteFullUniverseScreeningStore` keeps one append-only SHA-256 chain containing:

- cycle-start evidence;
- every partition attempt and failure;
- one immutable terminal result for each eligible instrument;
- publication; and
- cycle failures.

Completed instrument results are reused by a later run with the same cycle identifier. Retry budgets apply per invocation, while attempt numbers remain globally monotonic. Existing publications are replayable and can repair missing idempotent SLO or CIO-journal writes without requiring the original provider to remain active.

## Atomic publication boundary

Partial partitions and partial candidate sets are never submitted to the opportunity engine or CIO journal. A publication must reconcile:

```text
eligible instruments = screened instruments
screened instruments = candidates + analytical exclusions
```

Structural universe exclusions—such as unsupported asset classes or insufficient Version 1 liquidity—remain part of the immutable universe snapshot. Analytical exclusions explain why an otherwise eligible constituent did not become a candidate.

## Provider interfaces

Production adapters implement two narrow contracts:

- `UniverseMetricsProvider.fetch_metrics(snapshot)` returns point-in-time liquidity and analytical-coverage metrics; and
- `CandidateScreeningProvider.screen(constituent, as_of, opportunity_cost_return)` returns either a complete `CandidateDecisionRecord` or an explicit exclusion.

Candidate lineage, decision timestamp, symbol, instrument identifier, and opportunity cost are revalidated by the orchestrator.

## Command

```bash
python run_full_universe_screening.py \
  --cycle-id full-universe:2026-07-27 \
  --scheduled-for 2026-07-27T11:00:00+00:00 \
  --as-of 2026-07-27T12:00:00+00:00 \
  --knowledge-cutoff 2026-07-27T12:00:00+00:00 \
  --context deploy/opportunity-context.json \
  --metrics-provider licensed_market_adapter:build_metrics_provider \
  --candidate-provider production_candidate_adapter:build_candidate_provider
```

Factories are intentionally external to the core orchestrator. The command remains blocked until a real certified provider and production analytical adapters are configured.
