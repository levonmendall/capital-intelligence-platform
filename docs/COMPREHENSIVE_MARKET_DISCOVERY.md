# Comprehensive Market Discovery

The canonical paper CIO no longer depends on the fixed 14-instrument direct-market list. Before each governed CIO publication, six independent discovery lanes scan the configured provider catalogs and nominate a bounded point-in-time shortlist:

- international common and preferred equities across configured global exchanges;
- complete provider-listed spot-FX pairs;
- broader provider-listed spot crypto assets;
- dated futures chains across equity-index, rates, energy, metals, and currency roots;
- direct USD bonds; and
- long-premium calls and puts selected from current option chains.

The existing broad U.S.-company scan remains a seventh lane. The 15 strategic wrappers remain implementation alternatives and portfolio anchors, not the boundary of what the CIO may analyze.

## Operating sequence

1. Scan the complete configured catalog for each lane.
2. Apply structural identity, instrument-type, expiry, currency, and provider filters.
3. Retain every current holding and unresolved outcome-tracking symbol.
4. Deepen a bounded shortlist with point-in-time price history and current market evidence.
5. Rank within each lane using multi-horizon return, liquidity, volatility, and drawdown.
6. Publish the exact selected instrument identifiers into the daily certified eligible universe.
7. Send candidates through the existing Opportunity Engine, six-specialist committee, CIO, construction, authorization, paper execution, reconciliation, and append-only portfolio accounting path.

Discovery cannot choose an action, size a position, construct a portfolio, authorize execution, promote policy, or enable real money.

## Asset-specific controls

- **Global equities:** direct local listings, exchange-local sessions, foreign-currency translation, and a 3% initial instrument ceiling.
- **Spot FX:** unlevered 24/5 exposure and a 5% instrument ceiling.
- **Spot crypto:** unlevered 24/7 exposure and a 2.5% instrument ceiling.
- **Dated futures:** explicit contract identity, expiry, multiplier, lifecycle and roll models; notional remains fully collateralized with no margin leverage; 5% instrument ceiling.
- **Direct bonds:** dealer-session evidence, direct bond identity, maturity/coupon lifecycle, USD settlement, and a 5% instrument ceiling.
- **Options:** long-premium calls or puts only, exact strike and expiry, no naked short options, maximum loss limited to premium, no margin borrowing, and a 1% instrument ceiling.

Portfolio-level class, currency, liquidity, turnover, cash, drawdown, concentration, and gross-leverage controls remain independently binding and may reduce every initial target further.

## Providers and failure behavior

EODHD directories supply broad global-security, FX, crypto, and bond catalogs. Yahoo chart endpoints provide public underlying-history evidence. Defined-risk options use authenticated Databento `OPRA.PILLAR` definitions and daily OHLCV from the latest completed session, avoiding any claim of unlicensed live OPRA access. Dated futures use explicit exchange contract symbols and can be upgraded to Databento-native evidence without changing the discovery contract. Provider-native observations retain source identifiers and timestamps.

A missing lane cannot be silently treated as “no opportunity.” Complete discovery fails closed for that CIO publication, while the application remains available and explains which lane lacked certifiable evidence. Real-money authority remains disabled.
