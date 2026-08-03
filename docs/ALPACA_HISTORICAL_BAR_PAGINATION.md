# Alpaca historical-bar pagination

## Production incident

The August 3, 2026 canonical CIO retry progressed beyond the EODHD and SEC evidence
repairs and reached authenticated Alpaca IEX historical bars. The request covered a
broad listed universe and ten years of daily history. Alpaca continued returning valid
page tokens, but the client stopped after a fixed 100 pages and failed the entire
cross-market evidence collection.

The fixed count was not an evidence-quality boundary. The number of legitimate pages
depends on the symbol count, time range, timeframe, and page size. A broad universe can
therefore exceed 100 pages without any provider corruption or missing evidence.

## Correction

Production paper evidence now uses `CompleteHistoricalAlpacaPaperClient`:

1. Every requested symbol remains in scope.
2. The requested start, end, timeframe, adjustment, IEX feed, and ascending order remain
   unchanged.
3. Symbols are divided into deterministic batches sized from the requested timeframe,
   date range, and page limit, with an absolute maximum of 200 symbols per batch.
4. Each batch receives a finite page budget derived from its theoretical wall-clock
   record count rather than a fixed 100-page ceiling.
5. Pagination must make progress: a token without any returned bars blocks collection.
6. Repeated page tokens block collection rather than creating an infinite loop.
7. A batch exceeding its data-derived budget remains fail-closed and reports the batch
   size, timeframe, page budget, and policy version.
8. Results are reassembled in the original normalized symbol order without shortening
   history or fabricating bars.

## Governance boundary

This change does not reduce the universe, shorten the ten-year evidence window, lower a
minimum-history rule, change screening, alter an investment threshold, create a
candidate, authorize the CIO, modify construction, execute an order, or enable real
money. It only allows valid Alpaca pagination to finish while preserving explicit
failure for token cycles, non-progress, malformed bars, or an exceeded data-derived
budget.
