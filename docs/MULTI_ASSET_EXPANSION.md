# Governed Multi-Asset Expansion

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Product objective

Crypto, foreign exchange, and global listed markets extend the opportunity set under the same sole `COMPOUNDING` mandate. They do not create a crypto mandate, currency mandate, global mandate, tactical mandate, or user-selectable investment philosophy.

Development remains open. The investment process is not frozen and the product is not declared test ready by this expansion foundation.

## Authority boundary

An asset class may appear in identity, market-data, macro, or Environment evidence without being eligible for a portfolio recommendation. Direct paper recommendation requires an active, unexpired `AssetClassApproval` with state `paper_eligible`.

The approval must prove the complete asset-specific capability stack:

- point-in-time identity and venue history;
- licensed and certified market data;
- valuation methodology;
- expected-return methodology;
- liquidity methodology;
- transaction-cost and slippage methodology;
- portfolio risk and exposure methodology;
- paper-execution methodology;
- custody and settlement representation;
- living-thesis methodology;
- outcome-evaluation methodology;
- approved venues and jurisdictions;
- supported quote currencies and USD conversion boundary;
- source identifiers, versions, limitations, and governance record.

A symbol, provider response, model output, or new enum value is never sufficient approval.

## Lifecycle states

| State | Permitted use |
| --- | --- |
| `evidence_only` | Environment and cross-market evidence only |
| `research_approved` | Offline and shadow research; no CIO action |
| `paper_eligible` | May enter canonical screening and paper portfolio decisions when all other gates pass |
| `suspended` | New screening and actions blocked while evidence is investigated |
| `revoked` | Direct recommendation prohibited |

Only `paper_eligible` authorizes direct recommendation scope. It does not authorize live trading.

## Initial market boundaries

### Crypto

Initial direct scope is spot exposure only. Perpetuals, futures, options, leverage, staking, lending, yield products, privacy assets, and decentralized-finance protocols remain evidence-only until separately governed.

Required implementation characteristics include:

- continuous 24/7 market sessions;
- venue-specific identity and quote lineage;
- qualified digital-asset custody representation;
- fragmentation-aware liquidity and cost modeling;
- stablecoin and quote-currency risk treatment;
- on-chain/network and fork/event evidence;
- venue outage, halt, withdrawal, and depeg controls; and
- no assumption that repeated vendor reports are independent facts.

### Foreign exchange

Initial direct scope is unlevered spot FX paper exposure. Forwards, swaps, options, carry leverage, margin, and emerging-market convertibility risk remain evidence-only until separately governed.

Required implementation characteristics include:

- continuous 24/5 session behavior;
- explicit base and quote currencies;
- USD portfolio translation at the same point-in-time cutoff;
- prime-broker style paper settlement representation;
- rollover, holiday, fixing, spread, and liquidity-window controls;
- central-bank, rates, balance-of-payments, and funding evidence; and
- no hidden leverage through notional sizing.

### Global listed markets

Initial direct scope is liquid developed-market listed equities and listed funds on explicitly approved exchanges. Local derivatives, depositary-receipt substitutions, frontier markets, restricted shares, and inaccessible listings remain evidence-only until separately governed.

Required implementation characteristics include:

- issuer-to-listing identity across venues and currencies;
- historical listings, delistings, corporate actions, and benchmark membership;
- local exchange calendars and holidays;
- local accounting and filing availability boundaries;
- withholding-tax and transaction-tax assumptions where applicable;
- currency translation and FX contribution attribution;
- local liquidity, settlement, and market-access controls; and
- duplicate economic-exposure detection across primary listings and depositary receipts.

## Canonical software authority

`SQLiteAssetClassApprovalStore` is the append-only governance record. It uses a contiguous SHA-256 chain and database triggers that reject updates and deletes.

`AssetClassScopeAuthority` resolves the latest active approval at the decision timestamp and checks the candidate venue and jurisdiction. Missing, expired, incomplete, suspended, revoked, mismatched, or integrity-invalid approval blocks direct recommendation.

`RecommendationUniversePolicy` preserves the existing U.S. equity, U.S. ETF, and short-duration Treasury scope. Expanded markets require the additional asset-class authority and an explicit point-in-time timestamp.

`MultiAssetUniverseBuilder` classifies international listings separately from U.S. listings and preserves the asset-class approval identifier in universe membership lineage. It returns the same downstream universe contracts so screening, production context, specialists, CIO synthesis, construction, thesis monitoring, and evaluation do not gain competing authority.

## Governance command

Append a reviewed approval:

```bash
python run_asset_class_governance.py \
  --approval reviewed-crypto-paper-approval.json
```

Inspect active market status:

```bash
python run_asset_class_governance.py --status
```

The status response permanently reports:

```text
 development_open = true
 test_ready = false
 real_money_authorized = false
```

Those fields cannot be changed merely by appending an asset-class approval.

## Required follow-on vertical slices

The governance foundation does not fabricate provider access or certify models. Each market still requires a complete vertical slice:

1. licensed provider onboarding and certification;
2. point-in-time security-master coverage;
3. market, fundamental, macro, and asset-specific evidence normalization;
4. asset-specific candidate construction;
5. complete-universe screening and reconciliation;
6. cross-currency canonical portfolio valuation;
7. asset-specific paper execution and reconciliation;
8. thesis monitoring and outcome evaluation;
9. resilience exercises;
10. technical burn-in and human governance review.

The product remains in development until all selected market slices satisfy those gates together.
