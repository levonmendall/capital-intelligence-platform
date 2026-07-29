# Ten-Year Historical Backfill and Canonical CIO Replay

The historical subsystem collects the broadest practical free/public research baseline while EODHD and Databento coverage is expanded. It is append-only, resumable, point-in-time bounded, and explicitly separate from execution authority.

## Current sources

- FRED/ALFRED observations and vintage availability metadata when `FRED_API_KEY` is configured.
- SEC EDGAR company facts with filing dates as the availability boundary.
- Coinbase Exchange daily spot bars for configured crypto pairs.
- CFTC Traders in Financial Futures positioning records.
- Treasury Fiscal Data debt-to-the-penny history.
- World Bank annual macro indicators.
- Federal Register document metadata.
- Stooq public daily market history as a non-strict, research-only bridge.
- GDELT news discovery metadata for its available recent window; it is not represented as ten years of full-text news.

Every record carries observation, availability, and retrieval timestamps; a deterministic content hash; source and dataset identity; limitations; and a strict-replay eligibility flag.

## Commands

Run or resume the default ten-year collection:

```bash
python run_historical_backfill.py --report historical-backfill-report.json
```

Run the production `CanonicalCIOCycle` over monthly historical cutoffs using the complete available research archive:

```bash
python run_canonical_historical_replay.py \
  --cadence monthly \
  --initial-portfolio-value 250000 \
  --report canonical-historical-replay.json
```

Use only records carrying certified historical availability boundaries:

```bash
python run_canonical_historical_replay.py \
  --cadence monthly \
  --strict-only \
  --report canonical-historical-replay-strict.json
```

Strict mode currently emphasizes sources such as Coinbase, FRED/ALFRED, SEC EDGAR, and Federal Register records. Stooq, World Bank, CFTC, Treasury, and GDELT records are excluded when their exact historical availability boundary is not certified.

The earlier momentum-only shadow engine remains available as a diagnostic baseline:

```bash
python run_historical_shadow_replay.py \
  --cadence monthly \
  --report historical-shadow-replay.json
```

The always-on persistent loop runs collection first and canonical replay second:

```bash
python run_historical_backfill.py --loop
```

## What canonical replay now does

For every weekly or monthly cutoff, the adapter:

1. Resolves only records available by the cutoff.
2. Reconstructs historical prices, volatility, drawdown, breadth, liquidity, and macro context.
3. Creates production-domain `CandidateDecisionRecord` objects.
4. Builds independent macro, market, forecast, valuation, portfolio, and evidence-governance inputs.
5. Invokes the actual production `CanonicalCIOCycle` for opportunity qualification, six-specialist review, CIO synthesis, portfolio construction, thesis creation, evidence freezing, and briefing generation.
6. Applies only the resulting target weights to an isolated historical research portfolio.
7. Marks that portfolio forward to the next cutoff and records the next decision.
8. Stores the result at `manifests/latest-canonical-replay.json`.

The replay begins with the configured research capital, defaulting to `$250,000`. It does not read or mutate the live canonical portfolio database.

## Completion evidence

The scheduled and main-branch GitHub run publishes the commit status context:

```text
historical-replay/canonical-cio
```

The status is set to `pending` when collection begins. A successful completion description contains credential-free counts in this form:

```text
records=<written> strict=<strict records> canonical=<invoked>/<total> blocked=<blocked>
```

The complete compressed archive, backfill report, legacy shadow report, and canonical replay report are also retained as the run artifact. No provider response bodies, credentials, or archive contents are committed to the repository.

The persistent app exposes the latest canonical manifest in the History surface under **Historical learning**. It shows invocation coverage and blocked cutoffs but does not represent the isolated research portfolio as verified performance.

## Evidence boundaries

Canonical replay is available in two modes:

- **Strict replay:** includes only records whose historical availability boundary is certified by the adapter.
- **Research bridge:** also includes clearly labeled non-strict public history, allowing broader stock and ETF evaluation while paid provider coverage is expanded.

A cutoff is recorded as blocked rather than fabricated when it lacks enough observations or required inputs. A source outage does not erase already collected evidence and does not stop other sources from running.

U.S. equities remain subject to the production evidence-governance rule requiring point-in-time normalized company analysis. Where the current free archive cannot construct that full packet, the Fundamental/Valuation and Evidence Governance specialists may abstain or veto the stock. Crypto and ETF candidates can use governed asset-specific valuation evidence. Expanded EODHD and Databento history, corporate actions, delistings, and security-master data will progressively replace research bridges and increase strict coverage.

## Persistent deployment variables

- `CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR`, normally `<data-dir>/historical_replay`
- `CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG`
- `CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS`, minimum 3600 and default 86400
- `CAPITAL_INTELLIGENCE_HISTORICAL_MAX_RECORDS_PER_SOURCE`
- `CAPITAL_INTELLIGENCE_CANONICAL_HISTORICAL_REPLAY_ENABLED`, default `true`
- `CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_CADENCE`, `weekly` or `monthly`
- `CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_STRICT_ONLY`, default `false`
- `CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_MINIMUM_OBSERVATIONS`, default `63`
- `CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_MAXIMUM_CANDIDATES`, default `25`
- `CAPITAL_INTELLIGENCE_CANONICAL_REPLAY_INITIAL_VALUE`, default `250000`
- `FRED_API_KEY`
- `SEC_USER_AGENT`

## Permanent safety boundary

Historical replay is a research evaluation surface. Every report permanently states:

```text
research_only = true
execution_authorized = false
paper_execution_authorized = false
real_money_authorized = false
policy_promotion_authorized = false
performance_claims_authorized = false
```

The replay cannot submit an Alpaca order, change the active paper portfolio, alter the production CIO policy, promote a challenger, or present incomplete research results as verified investment performance. Historical target weights are simulated inside the historical archive only.
