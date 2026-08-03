# Equity discovery resource governance

## Production incident

The August 3, 2026 production retry progressed through the provider and pagination
repairs, then the Render instance exited with status 137. The active architecture had
collapsed two distinct stages of the governed funnel:

1. broad eligible-universe review; and
2. full decision-evidence preparation.

Every liquid company that passed the inexpensive identity, snapshot, price, and
liquidity screen was receiving both multi-horizon discovery history and the later
10-year candidate-evidence package. The service also runs the API, Streamlit,
historical backfill, backup, readiness watchdog, and paper operator in one container.
Retaining the complete bar payload for every passing company therefore created an
unbounded memory requirement unrelated to investment quality.

The first resource correction imposed fixed 400-name and 64-name admission cohorts.
That prevented memory exhaustion, but it also meant ranking could stop an otherwise
eligible company before complete evidence and specialist qualification. The production
resource control therefore became an investment-consideration limit.

## Complete streaming correction

The U.S.-equity lane now preserves complete consideration through a staged, versioned
streaming funnel:

1. Every eligible Alpaca/SEC-listed company remains inside broad identity and current
   snapshot review. No maximum snapshot-universe count is applied by default.
2. Objective price and dollar-liquidity floors determine whether a company proceeds.
   Current movement and liquidity rank processing order only.
3. Every company passing that objective screen receives 550-day multi-horizon analysis.
4. Discovery history is retrieved and converted to compact features in batches of at
   most 25 symbols; each raw batch is released before the next request.
5. Every company with sufficient point-in-time history proceeds to the complete
   ten-year candidate-evidence lane. There is no default 400-name or 64-name cutoff.
6. Ten-year listed-market bars and quotes are collected in bounded batches of at most
   ten symbols. Each completed symbol is written to a cycle-local append-only SQLite
   spool on the configured data disk before the next batch is requested.
7. SEC Company Facts are collected and persisted one issuer at a time. Evidence builders
   read bars, quotes, and facts lazily by symbol rather than retaining the complete raw
   provider payload in process memory.
8. Current holdings and tracked unresolved theses remain mandatory and fail closed when
   their evidence is incomplete.
9. The downstream evidence, opportunity, specialist, CIO, construction, and paper
   execution gates remain unchanged. Complete consideration does not imply qualification.

Explicit count limits remain accepted only as compatibility/test overrides. The
production default is uncapped at the snapshot, deep-analysis, and decision-evidence
admission stages.

## Persistence and cleanup

The evidence spool is an operational buffer, not an investment authority:

- entries are append-only and content-hashed by namespace and symbol;
- a conflicting second write for the same symbol is rejected;
- completed provider records are available through read-only lazy mappings;
- the spool contains no credentials or authorization state;
- normal completion removes the cycle-local spool after compact governed evidence has
  been built; abandoned spools older than two days are removed at the next collection;
- the canonical append-only screening and production-context stores remain the final
  decision records.

## Governance boundary

This correction does not lower an investment threshold, change the ranking formula,
shorten an evidence window, remove holding review, manufacture evidence, authorize the
CIO, alter construction, execute an order, or enable real money. It removes arbitrary
candidate-count admission limits while retaining a finite provider-payload memory
envelope.
