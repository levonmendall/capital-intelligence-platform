# Ten-Year Historical Backfill and Shadow Replay

The historical subsystem collects the broadest practical free/public research baseline while EODHD and Databento coverage is expanded. It is append-only, resumable and explicitly separate from execution authority.

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

Every record carries observation, availability and retrieval timestamps, a deterministic content hash, source/dataset identity, quality, limitations and a strict-replay eligibility flag.

## Commands

Run or resume the default ten-year collection:

```bash
python run_historical_backfill.py --report historical-backfill-report.json
```

Generate monthly research-only shadow decisions using only strict point-in-time records:

```bash
python run_historical_shadow_replay.py --cadence monthly --report historical-shadow-replay.json
```

The always-on loop is available for a persistent host:

```bash
python run_historical_backfill.py --loop
```

## Persistent deployment variables

- `CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR`, normally `<data-dir>/historical_replay`
- `CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG`
- `CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS`, minimum 3600 and default 86400
- `CAPITAL_INTELLIGENCE_HISTORICAL_MAX_RECORDS_PER_SOURCE`
- `FRED_API_KEY`
- `SEC_USER_AGENT`

## Safety and evidence boundary

The shadow engine does not call the canonical CIO, promote a policy, create a paper order, authorize real money or publish performance claims. Stooq, World Bank, CFTC and Treasury records remain non-strict where exact historical publication timestamps or vintages are unavailable. GDELT is discovery evidence requiring corroboration and has a shorter historical window.

A complete canonical CIO replay still requires the expanded EODHD/Databento universe, a survivorship-safe point-in-time security master, delistings, corporate actions, historical liquidity/costs and complete specialist evidence. The current subsystem makes useful historical learning available now without pretending those missing controls already exist.
