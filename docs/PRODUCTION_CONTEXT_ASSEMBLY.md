# Production Context Assembly

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

`RepositoryProductionCanonicalCIOContextProvider` is the concrete in-repository adapter that supplies `ProductionCanonicalCIOContext` to the production scheduler. It converts persisted, governed records into the exact non-candidate inputs required by `CanonicalCIOCycle`.

The adapter does not screen securities, modify candidates, infer missing exposures, substitute legacy portfolio state, or manufacture evidence.

## Persisted authorities

The provider reads only:

- `SQLiteFullUniverseScreeningStore` for the complete screening publication and its point-in-time cycle boundary;
- `SQLiteCanonicalPortfolioStore` for the exact-time cash, holdings, valuations, and implementation lineage; and
- `SQLiteProductionContextStore` for certified macro, market, fundamental, valuation, exposure, holding, cash, source-version, and model-version evidence.

All three stores are integrity-verified before assembly.

## Assembly behavior

For one decision timestamp, the provider:

1. Loads exactly one production-context evidence snapshot for the configured canonical portfolio.
2. Resolves its persisted screening publication and cycle-start boundary.
3. Requires matching `as_of` timestamps and knowledge cutoffs.
4. Reconstructs candidates only from the publication payloads.
5. Uses the persisted qualified queue as the required candidate-context set.
6. Loads the canonical portfolio snapshot at the exact decision timestamp.
7. Constructs cash and every current holding as capital alternatives.
8. Adds each qualified screened candidate as a peer capital alternative.
9. Builds one `CandidateCycleContext` and one `CandidateExposureProfile` for each qualified candidate.
10. Emits a `ProductionContextManifest` containing publication, portfolio, context-evidence, evidence-identifier, source-version, and model-version lineage.

The opportunity engine excludes the candidate itself when comparing peer candidates. The immutable candidate record's stated opportunity cost remains checked against the baseline cash and current-holding alternatives, while the effective opportunity edge is measured against every other available use of capital.

## Failure boundary

Assembly fails closed for:

- absent or incomplete screening publications;
- invalid screening, portfolio, or context hash chains;
- timestamp or knowledge-cutoff disagreement;
- missing, extra, or duplicate candidate context;
- missing, extra, or duplicate holding context;
- stale, conditional, rejected, expired, or otherwise uncertified evidence;
- missing candidate exposure profiles;
- missing governed fundamental and valuation analysis for an equity candidate;
- absent or duplicate exact-time canonical portfolio snapshots;
- non-positive NAV or no positive cash alternative; or
- manifest disagreement with the persisted publication.

A failure prevents `CanonicalCIOCycle` from starting. No partial candidate set or legacy fallback is permitted.

## Configuration

The scheduler uses the repository provider by default:

```bash
export CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE=database/full_universe_screening.db
export CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE=database/canonical_portfolio.db
export CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE=database/production_context.db
export CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE=COMPOUNDING
python run_scheduler.py --once
```

`CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER=module:function` remains an optional controlled override. It cannot bypass executor validation.

## Validation

The integration test persists screening, portfolio, and production-context evidence records, constructs the repository provider, and invokes `ProductionCanonicalCIOExecutor` with the real journal-backed `CanonicalCIOCycle`. It verifies qualification, specialist analysis, CIO decisions, evidence snapshots, the daily briefing, journal integrity, stale-evidence rejection, exact candidate coverage, peer comparison, and retained source/model lineage.
