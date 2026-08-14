# Persistent Historical Evidence

The all-market CIO runtime separates reusable historical evidence from freshness-sensitive decision evidence.

## Reusable historical base

Daily historical bars already observed for an exact economic instrument may be retained on the persistent service disk. The store is keyed by asset class, exact instrument identity, provider capability/dataset scope, and observation timestamp. Rows and coverage metadata carry integrity digests, and future-dated writes are rejected.

The shared market-history router applies this base to every executable non-option lane that already uses governed redundant history: U.S. equities/ETFs, international equities, FX, crypto, futures, and exact-security fixed income. Options use the same store at the resumable option-history boundary.

## Decision-time refresh

A persistent base never authorizes a new CIO epoch by itself. Coverage records the cutoff through which the provider was most recently checked. Once that refresh boundary exceeds the configured historical-base age, the runtime must refresh before the cache can satisfy the new epoch.

For options, once a requested long history horizon (including the existing 365-day selection history) has been established, a later CIO epoch fetches only a bounded overlapping tail. The persisted long horizon remains intact and the refreshed tail is merged through the new point-in-time cutoff. If the required tail refresh cannot be obtained, the stale cache is not used.

For other routed daily-history lanes, a recently refreshed base can satisfy repeated diagnostics without repeating identical provider requests; an overdue base re-enters the existing provider router and remains fail-closed.

## Evidence that is never replaced by this cache

The persistent historical store does not replace current quotes, spreads, liquidity, implied volatility or Greeks, fundamentals, macro evidence, specialist analysis, CIO decisions, portfolio construction, or execution evidence. Existing freshness, screening, point-in-time, CIO-only authority, and paper-only controls remain unchanged.
