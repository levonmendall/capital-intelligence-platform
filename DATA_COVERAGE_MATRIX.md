# Data Coverage Matrix

Status vocabulary:

- **Monitored**: information can be observed or discussed.
- **Decision-certified**: point-in-time identity, evidence, provenance, freshness, rights, and required analytical domains are certified for CIO use.
- **Capability-certified**: the exact structural instrument also has a complete current Universal Capability Graph and an active append-only paper-eligibility certification.
- **Allocatable**: the exact instrument is capability-certified, survives CIO/construction authority, and has current paper execution, lifecycle, accounting, currency, and reconciliation support.

| Market/domain | Monitored | Decision certification | Paper allocation |
|---|---|---|---|
| U.S. macro/rates | Yes | FRED and other certified point-in-time observations only | Indirectly through any exact active-universe instrument whose thesis uses the evidence |
| U.S. equities and listed funds | Provider-driven complete catalog plus SEC identity where applicable | Per instrument; no 15-symbol or candidate-count ceiling | Bootstrap authority or exact dynamic UCG certification; then CIO/construction and universal share execution |
| International equities and funds | Complete certified provider catalog across configured and provider-neutral venues | Per instrument and venue | Exact dynamic UCG certification when identity, market data, custody, settlement, FX, execution and listed lifecycle capabilities are complete |
| Government bonds and credit | Sovereign-rate evidence, listed implementations, derivatives, and direct bonds from certified security catalogs | Benchmark-yield directories are evidence-only. Direct bonds require actual security identity, terms, pricing, liquidity, currency, lifecycle, and provenance | Listed funds proceed structurally as funds. Direct bonds remain fail-closed until maturity, coupon, duration, settlement, execution, accounting and reconciliation proof is complete |
| Commodities and precious metals | Spot, listed, and derivative structures may be represented | Asset-specific curves, carry, contract, liquidity, and risk evidence | Any exact capability-complete structure; futures additionally require expiry, roll, multiplier and margin proof |
| Foreign exchange | Spot, forwards, listed implementations, and certified structures | Pair, venue, settlement, carry, liquidity, and translation evidence | Capability-complete instruments with pair, financing, rollover and settlement proof; no UUP-only boundary |
| Crypto | Spot, tokens, stablecoins, listed implementations, and certified derivatives | Venue, custody, market structure, liquidity, and point-in-time evidence | Capability-complete instruments with continuous-session, denomination, venue and custody-simulation proof; no IBIT-only boundary |
| Real estate and alternatives | Listed and direct classified structures | Asset-specific identity, valuation, liquidity, and execution evidence | Capability-complete structural instruments; no VNQ/DBMF/BTAL-only boundary |
| Futures, options, and volatility | Complete certified contract catalogs may supplement bootstrap roots and underlyings | Contract, margin, lifecycle, roll, surface, payoff, and defined-risk evidence where applicable | Capability-complete exact contracts; options require strike/side/expiry, multiplier, assignment, Greeks and margin proof |
| Fundamentals and filings | SEC plus certified global sources | Point-in-time accounting and issuer evidence appropriate to the asset | Supports any candidate whose applicable evidence set is complete |
| Security master and reference | Provider-driven and certified provider-neutral catalogs | Stable identity, venue, currency, lifecycle, and corporate-action lineage | Exact active-universe publication plus active capability authority is required at decision time |
| Public events and news | Multiple official/public sources | Supporting evidence only | Never independently allocatable or action-authorizing |

## Production dynamic-authority path

The original 15 listed instruments remain bootstrap and regression anchors, not an exclusive universe. Production discovery may publish additional instruments. After full-universe screening completes, `ProductionCapabilityAuthority` builds exact point-in-time capability evidence and calls the append-only automatic eligibility factory. Dynamic instruments enter the production CIO ownership universe only while that certification is active.

The complete active publication is intentionally retained even when a dynamic certification is suspended. This preserves the ability to reduce or exit an already-owned instrument. New or increased exposure is blocked until the capability graph is complete again.

The canonical paper fill path now applies the universal asset-family contract on top of the mature multi-asset ledger. The ledger continues to own session, quote, liquidity, cash, position, fill, accounting and reconciliation controls. Universal quantity normalization covers shares, face-value units, contracts, base-currency units and crypto units.

## Global opportunity coverage accountability

Global rotation readiness is measured along two independent axes:

1. **Economic domain breadth** — equity, fixed income, credit, currency, commodity, crypto, real estate, volatility/derivatives and alternatives.
2. **Geographic breadth** — North America, Europe, Japan, developed Asia-Pacific and emerging markets, with global/non-geographic markets tracked separately.

A domain or region is not counted as ready merely because one symbol is visible. The reviewed set must have governed evidence and liquidity coverage, while forward-intelligence coverage is measured separately. This prevents a U.S.-heavy candidate set from being described as globally complete simply because it contains several asset classes.

`config/market_coverage_registry.v1.json` continues to certify market-family participation. The current `active-paper-universe.json` publication is the exact execution/reconciliation universe. `instrument-paper-eligibility.db` supplies the dynamic exact-instrument capability authority applied at production decision and new-exposure execution time.

EODHD `BOND` and `GBOND` benchmark directories are not executable security masters and remain excluded from investable discovery. Sovereign-rate observations remain available to the macro, valuation, risk, and CIO evidence path. Listed fixed-income funds continue through the normal listed-instrument capability stack. A provider-neutral catalog can restore direct fixed-income discovery automatically when it supplies actual bonds with the complete required capabilities.

Provider availability alone does not create ownership authority. Missing or stale evidence, incomplete capability, absent provider rights, unsupported execution, unresolved lifecycle/accounting, or failed reconciliation remains fail-closed. Conversely, code-level symbol, asset-class, instrument-type, candidate-count, exchange, futures-root, option-underlying, geography, or wrapper lists cannot independently exclude an otherwise certified and capability-complete instrument.
