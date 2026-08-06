# Data Coverage Matrix

Status vocabulary:

- **Monitored**: information can be observed or discussed.
- **Decision-certified**: point-in-time identity, evidence, provenance, freshness, rights, and required analytical domains are certified for CIO use.
- **Allocatable**: the exact instrument also has current liquidity, cost, construction, paper execution, custody, settlement, lifecycle, currency, and reconciliation capability.

| Market/domain | Monitored | Decision certification | Paper allocation |
|---|---|---|---|
| U.S. macro/rates | Yes | FRED and other certified point-in-time observations only | Indirectly through any exact active-universe instrument whose thesis uses the evidence |
| U.S. equities and listed funds | Provider-driven complete catalog plus SEC identity where applicable | Per instrument; no 15-symbol or candidate-count ceiling | Any active, tradable, capability-complete listed instrument in the exact active universe |
| International equities and funds | Complete certified provider catalog across configured and provider-neutral venues | Per instrument and venue | Direct or listed implementation when identity, market data, custody, settlement, FX, and execution capability are complete |
| Government bonds and credit | Sovereign-rate evidence, listed implementations, derivatives, and direct bonds from certified security catalogs | Benchmark-yield directories are evidence-only. Direct bonds require actual security identity, terms, pricing, liquidity, currency, lifecycle, and provenance | Listed funds and other exact capability-complete structures may be allocated now. Direct bonds remain fail-closed until custody, settlement, execution, accounting, and reconciliation also pass |
| Commodities and precious metals | Spot, listed, and derivative structures may be represented | Asset-specific curves, carry, contract, liquidity, and risk evidence | Any exact capability-complete structure; no wrapper-only rule |
| Foreign exchange | Spot, forwards, listed implementations, and certified structures | Pair, venue, settlement, carry, liquidity, and translation evidence | Capability-complete instruments; no UUP-only boundary |
| Crypto | Spot, tokens, stablecoins, listed implementations, and certified derivatives | Venue, custody, market structure, liquidity, and point-in-time evidence | Capability-complete instruments; no IBIT-only boundary |
| Real estate and alternatives | Listed and direct classified structures | Asset-specific identity, valuation, liquidity, and execution evidence | Capability-complete instruments; no VNQ/DBMF/BTAL-only boundary |
| Futures, options, and volatility | Complete certified contract catalogs may supplement bootstrap roots and underlyings | Contract, margin, lifecycle, roll, surface, and defined-risk evidence where applicable | Capability-complete exact contracts; no fixed root, underlying, or 20/24-contract ownership ceiling |
| Fundamentals and filings | SEC plus certified global sources | Point-in-time accounting and issuer evidence appropriate to the asset | Supports any candidate whose applicable evidence set is complete |
| Security master and reference | Provider-driven and certified provider-neutral catalogs | Stable identity, venue, currency, lifecycle, and corporate-action lineage | Exact active-universe publication is required at execution time |
| Public events and news | Multiple official/public sources | Supporting evidence only | Never independently allocatable or action-authorizing |

`config/market_coverage_registry.v1.json` certifies market-family participation. The current certified `active-paper-universe.json` publication is the exact instrument-level paper authority. The original 15 listed instruments are a bootstrap and regression baseline, not an exclusive scope.

EODHD `BOND` and `GBOND` benchmark directories are not executable security masters and are excluded from investable discovery. Sovereign-rate observations remain available to the macro, valuation, risk, and CIO evidence path. Listed fixed-income funds such as the governed baseline instruments continue through the normal listed-instrument capability stack. A provider-neutral catalog can restore direct fixed-income discovery automatically when it supplies actual bonds with the complete required capabilities.

Provider availability alone does not create ownership authority. Missing or stale evidence, incomplete capability, absent provider rights, unsupported execution, or unresolved reconciliation remains fail-closed. Conversely, code-level symbol, asset-class, instrument-type, candidate-count, exchange, futures-root, or option-underlying lists cannot independently exclude an otherwise certified and capability-complete instrument.
