# Universal Governed Market Scope

## Governing rule

> **Every classified liquid public market may compete for capital, but no individual instrument may receive paper capital until its exact point-in-time implementation capability is certified.**

The sole mandate remains `COMPOUNDING`. Asset classes do not create separate portfolios, objectives, committees, or user-selected strategies.

## Universal availability

The governed paper-allocation taxonomy includes:

- U.S. and international equities and listed funds;
- sovereign, agency, municipal, investment-grade, high-yield, and other public fixed income;
- cash and cash equivalents;
- commodities and precious metals;
- foreign exchange;
- crypto and digital assets;
- listed real estate and infrastructure;
- futures and other exchange-traded contracts;
- listed options;
- volatility instruments; and
- other classified liquid public alternatives.

`OTHER` is not an investable catch-all. An instrument must first be classified into a governed economic exposure and instrument structure. Private, stale-priced, inaccessible, or materially illiquid assets remain outside direct paper execution until the platform can represent their economics honestly.

## Capability—not asset-class—boundary

Core plain U.S. equities, plain U.S. ETFs, cash, and short-duration Treasury equivalents retain direct policy eligibility. Every non-core market and every complex wrapper requires an active, unexpired `AssetClassApproval` with state `paper_eligible`.

The approval proves:

- point-in-time identity, venue, contract, and corporate-action history;
- licensed and certified prices, quotes, liquidity, and reference data;
- valuation and expected-return methodology;
- risk, concentration, correlation, leverage, and margin methodology;
- transaction-cost, slippage, carry, roll, and financing methodology;
- paper execution, market sessions, holidays, halts, and reconciliation;
- custody, clearing, settlement, currency, tax, and collateral representation;
- contract lifecycle, expiration, exercise, assignment, delivery, and roll behavior where applicable;
- living-thesis monitoring and point-in-time outcome evaluation; and
- approved instrument types, leverage limits, venues, jurisdictions, quote currencies, source versions, and limitations.

A U.S.-listed wrapper does not bypass the governance of its economic exposure. Leveraged, inverse, synthetic, derivative-based, crypto, commodity, volatility, or alternative ETFs are routed to the corresponding capability approval.

## Instrument states

| State | Permitted use |
| --- | --- |
| `evidence_only` | Environment and cross-market evidence only |
| `research_approved` | Offline and shadow decisions; no active CIO action |
| `paper_eligible` | May enter certified screening, construction, and paper execution when every instrument gate passes |
| `suspended` | New exposure blocked while evidence or implementation is investigated |
| `revoked` | New exposure prohibited; an owned position may be reduce-only under certified execution lineage |

## Asset-specific operating requirements

### Equities, listed funds, real estate, and listed alternatives

Require primary-listing identity, local calendars, corporate actions, accounting and filing boundaries, local taxes, FX attribution, settlement, market access, and duplicate-exposure detection.

### Fixed income

Require instrument terms, accrued interest, clean and dirty pricing, yield, duration, convexity, ratings, calls, defaults, recovery, dealer liquidity, calendars, settlement, and benchmark lineage.

### Commodities and futures

Require spot-versus-futures separation, contract multipliers, margin, collateral, curve shape, carry, roll, expiry, delivery, position limits, session breaks, and underlying-market evidence. Initial paper futures are fully collateralized and cannot create portfolio leverage above the certified limit.

### Foreign exchange

Require explicit base and quote currencies, point-in-time USD translation, settlement and rollover, fixing and holiday controls, spread and liquidity windows, convertibility, and no hidden notional leverage.

### Crypto

Require 24/7 sessions, network and token identity, multi-venue validation, qualified custody representation, fragmentation-aware liquidity, stablecoin and quote-currency risk, forks and network events, and venue outage, withdrawal, halt, and depeg controls.

### Options and volatility

Require contract identity, multiplier, strike, expiry, exercise style, settlement, implied-volatility surface, Greeks, maximum loss, margin, assignment and exercise, corporate-action adjustment, liquidity, path dependency, and lifecycle/roll controls. Initial option paper allocation is limited to long, premium-funded, defined-risk positions until short-option and portfolio-margin authorities are separately certified.

## Canonical software authority

- `SQLiteAssetClassApprovalStore` is the append-only, SHA-256-chained governance record.
- `AssetClassScopeAuthority` resolves the latest active capability approval and validates instrument type, leverage, venue, and jurisdiction.
- `RecommendationUniversePolicy` routes all classified non-core instruments and complex wrappers through that authority.
- `MultiAssetUniverseBuilder` preserves instrument structure, economic exposure, leverage, derivative use, and approval lineage.
- `GovernedMultiAssetConstructionEngine` enforces class, currency, leverage, margin, and defined-risk constraints without changing CIO ranking.
- `MultiAssetPaperExecutionOrchestrator` applies asset-aware sessions, contract multipliers, quotes, FX, costs, ownership, and reconciliation.
- `CertifiedExecutionEligibilityAuthority` binds execution to the exact certified universe publication and permits unsupported legacy holdings only to be reduced or closed.

## Readiness boundary

All classified market families are available in the product architecture, but availability is not fabricated readiness. A market whose providers, models, approvals, or operating evidence are incomplete remains blocked at the instrument gate. The version-controlled data manifest intentionally declares every classified market `paper_eligible` in scope while its disabled provider requirements keep the overall readiness report blocked until onboarding and certification are real.

No approval or readiness status authorizes live trading, leverage beyond its certified limit, or performance claims.
