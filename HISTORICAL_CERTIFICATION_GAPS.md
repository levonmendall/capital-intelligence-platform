# Historical Certification Gaps

## Certification standard

A historical result is certifiable only when every decision input can be reconstructed as it was available at the cutoff, the eligible universe is survivorship-safe, execution inputs reflect the then-available market/session, and provider availability/licensing boundaries are explicit. Code-level `as_of` fields alone are insufficient.

| Domain | Existing foundation | Remaining certification evidence |
|---|---|---|
| Macro vintages/revisions | Point-in-time observation contracts; FRED adapter | ALFRED/vintage retrieval, release calendar, revisions and late corrections |
| Filings/fundamentals | SEC submissions/company facts | Acceptance timestamps, amendments/restatements, older archives, global filings, normalization-era versions |
| Listings/delistings | Security-master ingestion and append-only activation | Historical identifiers, listing/delisting dates, symbol changes, bankruptcies, venue migrations |
| Corporate actions | Data types/manifests | Splits, dividends, mergers, spin-offs, rights, tender events and adjustment methodology |
| Index membership | Benchmark domains declared | Effective/announcement dates and historical constituent membership |
| Liquidity/quotes | Market and execution models | Contemporaneous bid/ask/depth/volume, stale/closed market rules, venue coverage |
| Calendars/session state | Market-session controls | Historical holidays, half days, outages, DST, venue-specific sessions |
| FX/cross-currency | Cross-currency models | Historical executable FX, fixing selection, availability time, conversion costs |
| Crypto market structure | Venue adapters/validation config | Venue listings/delistings, forks, outages, 24/7 availability, consolidated/corroborated pricing |
| Derivatives | Contract/margin/surface models | Historical contract specs, rolls, margin schedules, settlement, expiries, surfaces |
| Provider availability | Provenance contracts | Exact product entitlement and adapter availability periods; no use before system/provider availability |
| Costs/borrow/taxes | Construction cost framework | Era-specific spreads, fees, borrow availability/rates, market impact assumptions |

## Current conclusion

Historical replay is research-grade infrastructure, not yet a certified basis for performance claims or automatic policy changes. Completion belongs to PR11; experiment use belongs to PR12.
