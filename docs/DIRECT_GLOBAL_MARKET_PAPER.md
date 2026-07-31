# Direct global-market paper operation

## Objective

Direct spot FX, direct spot crypto, and fully collateralized futures are first-class
paper opportunities. They compete with listed securities and cash inside the same
canonical CIO, construction, authorization, execution, and portfolio-accounting path.

There is no blanket market prohibition. A specific instrument is excluded only when
its current point-in-time evidence, liquidity, session, contract, lifecycle, custody,
or simulated-execution requirements are incomplete.

## Initial direct universe

The first governed scope covers liquid USD-quoted major FX pairs, Bitcoin and Ether,
and continuous research representations of major equity-index, Treasury, energy,
metals, and currency futures. The universe is versioned in
`config/direct_global_market_universe.json`.

## Evidence and monitoring

Public chart evidence is normalized into the same daily-bar and quote contracts used
by the existing CIO evidence builder. Crypto remains available continuously. Spot FX
and futures use a continuous weekday session model. The five-minute materiality
scanner continues operating when the U.S. cash market is closed whenever a governed
direct market is open.

Direct evidence can request a full canonical CIO reassessment. It cannot rank,
recommend, size, construct, or execute independently. Simulated top-of-book spreads
are conservative paper assumptions and remain explicitly distinguishable from
broker-native executable quotes.

## Provider-degradation boundary

Direct-market evidence is collected independently for each governed instrument. A
temporary outage affecting an unheld FX, crypto, or futures instrument records an
explicit exclusion for that instrument rather than suppressing the complete CIO
briefing and decision-status publication. Successfully collected listed and direct
market evidence can continue through the canonical opportunity, CIO, and construction
process.

The boundary remains fail-closed for current holdings. When a held instrument lacks
current mandatory evidence, the production context and CIO cycle remain blocked until
that evidence recovers. No stale mark, fabricated quote, or unsupported holding
conclusion is substituted.

## Paper implementation

Spot FX and spot crypto are unlevered. Futures are represented with explicit contract
multipliers and fully collateralized notional exposure. The initial paper system does
not use margin leverage. Every futures profile includes contract, collateral,
lifecycle, and roll model versions.

Execution remains internal and simulated. Public chart evidence is not represented as
broker-native execution evidence. Real-money authority remains disabled.

## Portfolio controls

The existing universal multi-asset construction and execution controls remain
authoritative:

- aggregate crypto limits;
- spot-FX and foreign-currency limits;
- futures class limits;
- maximum gross leverage of 1.0;
- defined-risk derivative requirements;
- exact eligible-universe lineage;
- turnover, cash, drawdown, quote-age, and reconciliation controls.

## Advancement path

Broker-native market data and paper routing may later replace the public evidence
adapter asset class by asset class. That replacement requires a separately validated
provider binding and must not weaken point-in-time, cost, contract, custody, or
portfolio controls.
